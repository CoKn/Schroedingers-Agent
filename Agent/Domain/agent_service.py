# 
from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

from Agent.Ports.Outbound.llm_interface import LLM

from Agent.Domain.goal_state_enum import GoalStatus
from Agent.Domain.utils.json_markdown import json_to_markdown, format_tool_output_for_llm
from Agent.Domain.utils.tool_docs import format_tool_docs, make_get_tool_docs
from Agent.Domain.llm_planner import LLMPlanner
from Agent.Domain.prompts.registry import REGISTRY
from Agent.Domain.plan import Tree, Node
from Agent.Domain.agent_prompt_config import AgentPrompts
from Agent.Domain.agent_lifecycle import AgentSession
from Agent.Domain.events import EventBus, AgentEvent, AgentEventType


logging.basicConfig(
    level=logging.DEBUG,                 
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

class AgentService:
    def __init__(self, llm: LLM, mcp, events: EventBus | None = None):
        self.llm = llm
        self.mcp = mcp
        self._tools_meta_cache: list[dict] | None = None
        self.planner = LLMPlanner(llm=self.llm, get_tool_docs=make_get_tool_docs(self.mcp))
        self.events = events or EventBus()


    async def generate_plan(self, session: AgentSession, goal: str, *, replan_from_node: Node | None = None,) -> dict:
        is_replan = replan_from_node is not None
        stage = "replanning" if is_replan else "planning"
        event_type = (
                AgentEventType.REPLANNING_STARTED
                if hasattr(AgentEventType, "REPLANNING_STARTED")
                else AgentEventType.PLANNING_STARTED
            )

        # get metadata for available tools
        try:
            session.tools_meta = self.mcp.get_tools_json()
        except Exception as e:
            logger.exception("Failed to retrieve tools metadata")
            await self.events.publish(AgentEvent(
                type=AgentEventType.ERROR,
                data={"stage": "planning", "error": f"tools_meta: {e}"},
            ))
            raise
            
        # publish: planning started
        start_payload = {
            "user_prompt": session.user_prompt,
            "goal": goal,
            "step_index": session.step_index,
        }
        if is_replan:
            start_payload["from_node_id"] = replan_from_node.id
            start_payload["from_node_value"] = replan_from_node.value

        await self.events.publish(
            AgentEvent(
                type=event_type,
                data=start_payload,
            )
        )

        tool_docs = format_tool_docs(session.tools_meta)

        # formulate mode
        if stage == "planning":
            spec = REGISTRY.get(*AgentPrompts.goal_decomposition)
            system_prompt = spec.render(tool_docs=tool_docs)
            llm_prompt = f"Goal: {goal}"

        elif stage == "replanning":
            previous_subtree = replan_from_node.to_dict(include_children=True)
            spec = REGISTRY.get(*AgentPrompts.goal_decomposition_replanning)
            system_prompt = spec.render(tool_docs=tool_docs,
                                        replan_goal=goal, 
                                        facts=self.planner._facts(session=session),
                                        latest_summary=session.last_observation,
                                        previous_subtree=previous_subtree,
                                        executed_actions=session.trace or [],
                                        )
            llm_prompt = f"Global goal: {session.user_prompt}"

        else:
            raise ValueError(f"Invalid planning stage: {stage}. Expected 'planning' or 'replanning'.")

        # send llm request and generate json tree
        response = await asyncio.to_thread(
            self.llm.call,
            prompt=llm_prompt,
            system_prompt=system_prompt,
            json_mode=True
            )
        
        # deserilise json plan to plan object
        try:
            parsed = json.loads(response)

            logger.debug("Parsed plan: %s", parsed)

            parsed_tree = Tree._parse_json_to_tree(parsed)

            # initial plan
            if not is_replan:
                new_tree = parsed_tree
                new_tree.revision = 1
                new_tree.parent_revision = None
                new_tree.replanned_from_node_id = None

            # replan
            else:
                if not session.plan:
                    raise ValueError("Cannot replan: no existing plan on session")
                if not parsed_tree.root:
                    raise ValueError("Replan produced an empty subtree")

                new_subtree_root = parsed_tree.root
                new_tree = session.plan.new_revision_with_subtree(
                    node_id=replan_from_node.id,
                    new_subtree_root=new_subtree_root,
                )

            # save plan info in session
            session.plan = new_tree
            session.plan_revisions.append(new_tree)


        except json.JSONDecodeError as e:
            logger.exception("JSON parsing failed for %s response", stage)
            await self.events.publish(
                AgentEvent(
                    type=AgentEventType.ERROR,
                    data={"stage": stage, "error": str(e)},
                )
            )
            raise ValueError(f"Failed to parse JSON response: {e}") from e
        except ValueError as e:
            logger.exception("Tree parsing / %s failed", stage)
            await self.events.publish(
                AgentEvent(
                    type=AgentEventType.ERROR,
                    data={"stage": stage, "error": str(e)},
                )
            )
            raise

        # extract executable plan
        session.executable_plan = session.plan.get_leaves()
        
        # publish: plan generated
        try:
            plan_summary = session.plan.root.to_dict(include_children=True) if session.plan and session.plan.root else None
        except Exception:
            plan_summary = None

        await self.events.publish(AgentEvent(
            type=AgentEventType.PLAN_GENERATED,
            data={
                "goal": goal,
                "step_index": session.step_index,
                "leaf_count": len(session.executable_plan or []),
                "revision": session.plan.revision,
                "parent_revision": session.plan.parent_revision,
                "replanned_from_node_id": session.plan.replanned_from_node_id,
                "is_replan": is_replan,
                "plan": plan_summary,
            }
        ))

        return new_tree


    async def plan_step(self, session: AgentSession) -> dict:
        """Plan the next action based on current goals and context.

        Modes:
        1. Completely planned: tool name + parameters available
        2. Partially planned: tool name available, parameters need generation
        3. No planning: both tool name and parameters need generation
        """

        if not session.executable_plan:
            raise ValueError("No executable goals available. Did you generate a plan?")

        # Take next goal from the queue
        session.active_goal = session.executable_plan.pop(0)
        goal = session.active_goal

        logger.debug(f"Processing goal: {goal.value}")

        # Event: goal selected for this step
        await self.events.publish(AgentEvent(
            type=AgentEventType.STEP_GOAL_SELECTED,
            data={
                "session_id": getattr(session, "id", None),
                "step_index": session.step_index,
                "goal_id": goal.id,
                "goal_value": goal.value,
            },
        ))

        # Prepare context note (reusable for all modes)
        context_note = self.planner.format_context_note(session)

        tool = goal.mcp_tool
        args = goal.tool_args

        # Mode 1: Completely planned (tool name + parameters)
        if tool and args is not None:
            logger.debug(f"Mode 1: Using pre-planned tool: {tool}")

            # Event: tool preplanned (tool + args already known)
            await self.events.publish(AgentEvent(
                type=AgentEventType.STEP_TOOL_PREPLANNED,
                data={
                    "session_id": getattr(session, "id", None),
                    "step_index": session.step_index,
                    "goal_id": goal.id,
                    "tool": tool,
                    "arguments": args,
                },
            ))

            decision = {
                "call_function": tool,
                "arguments": args,
            }

        # Mode 2: Partially planned (tool name only, need parameters)
        elif tool and args is None:
            logger.debug(f"Mode 2: Planned tool, generating parameters: {tool}")

            # Event: parameters needed
            await self.events.publish(AgentEvent(
                type=AgentEventType.STEP_TOOL_PARAMS_REQUESTED,
                data={
                    "session_id": getattr(session, "id", None),
                    "step_index": session.step_index,
                    "goal_id": goal.id,
                    "tool": tool,
                },
            ))

            decision = await self.planner.generate_tool_parameters(session, context_note)

        # Mode 3: No planning (need both tool name and parameters)
        else:
            logger.debug("Mode 3: No pre-planning, generating tool selection + parameters")

            # Event: full tool selection requested
            await self.events.publish(AgentEvent(
                type=AgentEventType.STEP_TOOL_SELECTION_REQUESTED,
                data={
                    "session_id": getattr(session, "id", None),
                    "step_index": session.step_index,
                    "goal_id": goal.id,
                },
            ))

            decision = await self.planner.generate_full_plan(session, context_note)

        return decision


    async def act(self, session: AgentSession, decision: str) -> str:
        fn_name = decision.get("call_function")
        if not fn_name:
            raise ValueError(f"Missing 'call_function' in planner decision: {decision}")

        fn_args = decision.get("arguments", {})
        
        try:
            # execute tool if given
            if hasattr(self.mcp, "execute_tool"):
                return await self.mcp.execute_tool(fn_name, fn_args)
            
            # find the right tool
            tool_info = next((t for t in getattr(self.mcp, "tools_registry", []) if t["name"] == fn_name), None)
            if not tool_info:
                return f"Tool '{fn_name}' not found"
            
            logger.debug(f"Tool info: {tool_info}")
            logger.debug(f"Tool: '{fn_name}' with parameter: {fn_args}")

            # execute tool by the name found before
            tool_result = await tool_info["session"].call_tool(fn_name, fn_args)
            if hasattr(tool_result, "content") and isinstance(tool_result.content, list) and tool_result.content:
                first = tool_result.content[0]
                return getattr(first, "text", str(first))
            return tool_result
        except Exception as e:
            logger.exception("MCP tool execution failed for %s with args %s", fn_name, fn_args)

            await self.events.publish(AgentEvent(
                type=AgentEventType.ERROR,
                data={
                    "stage": "tool_execution",
                    "tool": fn_name,
                    "arguments": fn_args,
                    "error": str(e),
                },
            ))
            error_payload = {
            "error": "tool_execution_error",
            "tool": fn_name,
            "arguments": fn_args,
            "message": str(e),
            }
            return json.dumps(error_payload, ensure_ascii=False)



    async def observe(self, session: AgentSession) -> str:

        # collect context about the last action
        tool = session.last_decision.get("call_function") if session.last_decision else ""
        args = session.last_decision.get("arguments", {}) if session.last_decision else {}
        preconds = getattr(session.active_goal, "assumed_preconditions", []) if session.active_goal else []
        effects = getattr(session.active_goal, "assumed_effects", []) if session.active_goal else []

        raw_obs = session.last_observation or ""
        formatted_obs = format_tool_output_for_llm(raw_obs)
        
        # build prompt
        spec = REGISTRY.get(*AgentPrompts.step_summary)
        plan_snapshot = [
            n.to_dict(include_children=False)
            for n in (session.executable_plan or [])
        ]
        
        step_summary_prompt = spec.render(
            user_prompt=session.user_prompt,
            current_goal=session.active_goal.value if session.active_goal else "",
            preconditions_block=preconds,
            effects_block=effects,
            tool=tool,
            args=json.dumps(args, ensure_ascii=False),
            last_observation=formatted_obs,
            plan=plan_snapshot
        )

        #TODO split system prompt into 2 parts: system prmpt and prompt
        # sending summary request to llm
        observation = await asyncio.to_thread(
            self.llm.call,
            prompt="",
            system_prompt=step_summary_prompt,
            json_mode=True,
        )

        return observation

    # TODO: add seperate check for termination
    def check_termination(self, session: AgentSession):
        pass

    async def run_cycle(self, session: AgentSession) -> str:
        """
        Run a single ReAct cycle: plan -> act -> observe.

        Returns:
            The raw JSON summary string produced by the LLM in `observe`,
            or a synthetic summary JSON when the planner decides to terminate
            without executing a tool.
        """
        # increment step index
        session.step_index = getattr(session, "step_index", 0) + 1
        if getattr(session, "trace", None) is None:
            session.trace = []

        # plan
        decision: dict = await self.plan_step(session)
        if decision is None:
            decision = {}
        session.last_decision = decision

        terminate_flag = bool(decision.get("terminate"))
        reason = decision.get("reason")

        # case 1: planner says goal is completed
        if terminate_flag and reason == "goal completed":
            session.goal_reached = True

            summary_json = {
                "summary": "Goal marked as reached by planner (no tool call executed).",
                "goal_reached": True,
                "terminate": True,
                "reason": "goal completed",
                "ready_to_proceed": False,
                "facts_generated": [],
            }
            summary_raw = json.dumps(summary_json)

            # record in trace
            session.trace.append({
                "step": session.step_index,
                "goal": session.active_goal.value if session.active_goal else None,
                "decision": decision,
                "tool_result": None,
                "summary": summary_json,
            })

            return summary_raw

        # case 2: planner terminates for some other reason
        if terminate_flag and reason != "goal completed":
            # session.goal_reached = True
            # setattr(session, "terminate_reason", reason)

            summary_json = {
                "summary": f"Planner requested termination due to: {reason or ''}",
                "terminate": False,
                "reason": reason or "",
                "ready_to_proceed": False,
                "facts_generated": [],
            }
            summary_raw = json.dumps(summary_json)

            logger.warning(summary_raw)

            session.trace.append({
                "step": session.step_index,
                "goal": session.active_goal.value if session.active_goal else None,
                "decision": decision,
                "tool_result": None,
                "summary": summary_json,
            })

            return summary_raw

        # case 3: normal tool execution path
        if "call_function" not in decision:
            raise ValueError(
                f"Planner decision has neither 'terminate' nor 'call_function': {decision}"
            )

        await self.events.publish(AgentEvent(
            type=AgentEventType.STEP_DECISION_READY,
            data={
                "session_id": getattr(session, "id", None),
                "step_index": session.step_index,
                "goal_id": session.active_goal.id if session.active_goal else None,
                "decision": decision,
            },
        ))

        # act
        tool_result = await self.act(session, decision)
        session.last_observation = tool_result

        await self.events.publish(AgentEvent(
            type=AgentEventType.STEP_TOOL_EXECUTED,
            data={
                "session_id": getattr(session, "id", None),
                "step_index": session.step_index,
                "goal_id": session.active_goal.id if session.active_goal else None,
                "tool": decision.get("call_function"),
            },
        ))

        # observe
        summary_raw = await self.observe(session)

        await self.events.publish(AgentEvent(
            type=AgentEventType.STEP_SUMMARY_RECEIVED,
            data={
                "session_id": getattr(session, "id", None),
                "step_index": session.step_index,
                "goal_id": session.active_goal.id if session.active_goal else None,
                "summary_raw": summary_raw,
            },
        ))

        # mark leaf goal completed after one execution cycle
        if session.active_goal:
            session.active_goal.status = GoalStatus.COMPLETED

        # attach summary to trace
        try:
            summary_json = json.loads(summary_raw)
        except json.JSONDecodeError:
            summary_json = {"_parse_error": True, "raw": summary_raw}

        session.trace.append({
            "step": session.step_index,
            "goal": session.active_goal.value if session.active_goal else None,
            "decision": decision,
            "tool_result": tool_result,
            "summary": summary_json,
        })

        return summary_raw


    async def loop_run(self, session: AgentSession):
        if getattr(session, "trace", None) is None:
            session.trace = []

        session.goal_reached = getattr(session, "goal_reached", False)
        session.step_index = getattr(session, "step_index", 0)
        max_steps = getattr(session, "max_steps", 10)
        replan_attempts = getattr(session, "replan_attempts", 0)
        max_replans = getattr(session, "max_replans", 3)

        # publish session started
        await self.events.publish(AgentEvent(
            type=AgentEventType.SESSION_STARTED,
            data={
                "session_id": getattr(session, "id", None),
                "user_prompt": session.user_prompt,
            },
        ))

        # generate initial plan if needed
        if not session.plan:
            plan = await self.generate_plan(session=session, goal=session.user_prompt)
            session.trace.append(plan)

        try:
            while (
                not session.goal_reached
                and session.step_index < max_steps
                and (session.executable_plan is not None and len(session.executable_plan) > 0)
            ):
                # one ReAct cycle: plan -> act -> observe
                summary_raw = await self.run_cycle(session)

                # decide termination / replanning based on the summary json
                try:
                    summary_json = json.loads(summary_raw)
                except json.JSONDecodeError:
                    summary_json = {}

                if isinstance(summary_json, dict):
                    # step summary can signal completion / termination
                    if summary_json.get("goal_reached"):
                        session.goal_reached = True

                    if summary_json.get("terminate"):
                        # if it's a normal completion, mark goal_reached 
                        reason = summary_json.get("reason")
                        if reason == "goal completed":
                            session.goal_reached = True
                        #TODO: check whats going on with session.goal_reached = True
                        # else:
                        #     session.goal_reached = True  # terminate loop on any termination
                        setattr(session, "terminate_reason", reason)

                    ready = summary_json.get("ready_to_proceed", True)

                    # replanning trigger
                    if (
                        not ready
                        and not session.goal_reached
                        and replan_attempts < max_replans
                    ):
                        # replan the current goal's subtree (simple choice)
                        replan_node = session.active_goal or session.plan.root

                        new_plan = await self.generate_plan(
                            session=session,
                            goal=replan_node.value if replan_node else session.user_prompt,
                            replan_from_node=replan_node,
                        )

                        session.trace.append(new_plan)

                        replan_attempts += 1
                        setattr(session, "replan_attempts", replan_attempts)

                        # continue main loop with new executable_plan
                        continue
            
            #TODO: change check to filter only tool traces.
            # keep a human-readable version of the agent's observations/facts
            facts_collected = []
            for cycle in session.trace: 
                if isinstance(cycle, dict):
                    summary = cycle.get("summary")
                    if isinstance(summary, dict):
                        fg = summary.get("facts_generated")
                        if isinstance(fg, list):
                            facts_collected.extend(fg)

            # You could also add observation history here if you like; for now we
            # just feed facts.
            final_prompt = f"Facts: {facts_collected}"

            final_summary = await asyncio.to_thread(
                self.llm.call,
                prompt=final_prompt,
                system_prompt="Answer the following question / summarise the agent's observations",
                json_mode=False,
            )
            return final_summary, session.trace

        except Exception as e:
            logger.exception("Error in loop_run")
            await self.events.publish(AgentEvent(
                type=AgentEventType.ERROR,
                data={"stage": "loop_run", "error": str(e)},
            ))
            return f"Agent error: {e}", getattr(session, "trace", [])