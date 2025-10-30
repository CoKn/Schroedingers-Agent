from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

from Agent.Domain.planning.llm_planner import LLMPlanner
from Agent.Domain.prompts.loader import load_all_prompts

load_all_prompts()

from Agent.Domain.prompts.registry import REGISTRY
from Agent.Domain.utils.json_markdown import json_to_markdown
from Agent.Domain.plan import Tree, Node
from Agent.Domain.agent_state_enum import AgentState
from Agent.Domain.planning_mode_enum import PlanningMode
from Agent.Ports.Outbound.llm_interface import LLM
from Agent.Domain.agent_lifecycle import (
    AgentSession,
    start,
    on_planned,
    on_executed,
    on_summarised,
    on_error,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ProgressCb = Callable[[str], None]


class AgentService:
    def __init__(self, llm: LLM, mcp):
        self.llm = llm
        self.mcp = mcp
        self.planner = LLMPlanner(llm=self.llm, get_tool_docs=self._get_tool_docs)
        # Maintain optional references to the active session to support helper methods
        self.session: AgentSession | None = None
        self._current_session: AgentSession | None = None

    # TODO: Move this function to the plan file into the Node class
    # --- helpers: plan recording & serialization ---
    def _node_to_dict(self, node: Node) -> dict:
        return {
            "value": node.value,
            "abstraction_score": node.abstraction_score,
            "status": node.status.name if node.status else None,
            "mcp_tool": node.mcp_tool,
            "tool_args": node.tool_args,
            "assumed_preconditions": node.assumed_preconditions,
            "assumed_effects": node.assumed_effects,
            "is_leaf": node.is_leaf(),
            "is_executable": node.is_executable(),
            "children": [self._node_to_dict(child) for child in (node.children or [])]
        }

    def _record_plan_event(self, session: AgentSession, event_type: str, payload: dict):
        """Append a plan-related event to the session trace and plan history."""
        # Ensure trace exists
        if getattr(session, "trace", None) is None:
            session.trace = []

        event = {
            "event": event_type,
            "step": getattr(session, "step_index", 0),
            "payload": payload,
        }
        session.trace.append(event)

        # Keep a compact rolling plan history as well (optional for downstream UIs)
        if not hasattr(session, "plan_history") or session.plan_history is None:
            session.plan_history = []
        session.plan_history.append({"event": event_type, "payload": payload})
    
    def _get_tool_docs(self, tool_name: str = None, session: AgentSession | None = None) -> str:
        """Get documentation for a specific tool or all tools.
        
        Args:
            tool_name: If provided, returns docs for only this tool.
                      If None, returns docs for all tools.
        """
        # Resolve a usable session reference
        sess = session or getattr(self, "session", None) or getattr(self, "_current_session", None)
        if not sess:
            raise ValueError("No active session available to retrieve tool docs")

        # Ensure tools metadata is available on the session
        if not getattr(sess, "tools_meta", None):
            try:
                sess.tools_meta = self.mcp.get_tools_json()
            except Exception as e:
                raise ValueError(f"Unable to retrieve tools metadata: {e}")

        if tool_name:
            # Find the specific tool
            for tool in sess.tools_meta:
                if tool['name'] == tool_name:
                    return f"{tool['name']}: {tool['description']}\nInput schema: {tool['schema']}"
            raise ValueError(f"Tool '{tool_name}' not found in available tools")
        else:
            # Return all tools
            return "\n\n".join(
                f"{t['name']}: {t['description']}\nInput schema: {t['schema']}" 
                for t in sess.tools_meta
            )

    # hierarchical planning 
    async def init_plan(self, session: AgentSession, initial=True):
        """Initialize hierarchical plan by decomposing the user goal into executable sub-goals."""
        if not session.tools_meta:
            session.tools_meta = self.mcp.get_tools_json()
            
        # 1. initial prompt is set as root of tree
        version = getattr(session, "prompt_profile", {}).get("goal_decomposition", "v1")
        spec = REGISTRY.get("goal_decomposition", version=version)
        # Pass session explicitly to avoid relying on instance state before it's set
        system_prompt = spec.render(tool_docs=self._get_tool_docs(session=session))
        
        # Incorporate recent observations and step summaries to guide (re-)planning
        # Reuse the same context note construction used for action planning
        
        # if inital planning only use goal else give previous observations as context
        if initial:
            prompt=f"Goal: {session.user_prompt}"
        else:
            context_note = self.planner.format_context_note(session)
            prompt= (
                f"Goal: {session.user_prompt}" +
                (f"\n\nContext from previous steps:\n{context_note}" if context_note else "")
            )

        
        # 2. run llm call to generate tree
        resp = await asyncio.to_thread(
            self.llm.call,
            prompt=prompt,
            system_prompt=system_prompt,
            json_mode=True,
        )

         # 3. parse response to tree class
        try:
            parsed = json.loads(resp)
            plan: Tree = Tree._parse_json_to_tree(parsed)

        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing failed: {e}")
            logger.error(f"Raw response: {repr(resp)}")
            raise ValueError(f"Failed to parse JSON response: {str(e)}")
        except ValueError as e:
            logger.error(f"Tree parsing failed: {e}")
            raise
       
        # 4. extract leaf nodes -> the sequence to execute
        session.plan = plan
        session.executable_plan = plan.get_leaves()

        # Record plan generation into trace/history
        try:
            plan_payload = {
                "kind": "hierarchical",
                "initial": bool(initial),
                "tree": self._node_to_dict(session.plan.root) if session.plan and session.plan.root else None,
                "leaf_count": len(session.executable_plan or []),
            }
            self._record_plan_event(session, "plan_generated", plan_payload)
        except Exception as e:
            logger.debug(f"Failed to serialize/record plan: {e}")

    async def run(self, session: AgentSession, progress: ProgressCb | None = None):
        """Single or multi-step run. Delegates to loop_run to avoid duplication.
        If session.max_steps <= 1, this behaves like a single-iteration call."""
        original_max = session.max_steps
        try:
            if original_max <= 1:
                session.max_steps = 1
            return await self.loop_run(session, progress)
        finally:
            session.max_steps = original_max

    async def _plan(self, session: AgentSession) -> dict:
        """Plan the next action based on current goals and context.
        
        Handles three planning modes:
        1. Completely planned: tool name + parameters available
        2. Partially planned: tool name available, parameters need generation
        3. No planning: both tool name and parameters need generation
        """
        # Store session reference for utility functions
        self.session = session
        
        # If no executable items remain, attempt to re-plan before concluding
        if not session.executable_plan or len(session.executable_plan) == 0:
            # Re-plan throttling to avoid thrash: only one re-plan per step and max N per run
            current_step = getattr(session, "step_index", 0)
            last_replan_step = getattr(session, "_last_replan_step", None)
            replan_attempts = getattr(session, "_replan_attempts", 0)
            max_replans = getattr(session, "_max_replans", 3)

            should_replan = True
            if last_replan_step is not None and last_replan_step == current_step:
                # Already re-planned this step; skip to reactive to avoid thrashing
                should_replan = False
            if replan_attempts >= max_replans:
                should_replan = False

            if should_replan:
                logger.debug("Executable plan empty; attempting re-plan (throttled)")
                try:
                    await self.init_plan(session, initial=False)
                    setattr(session, "_last_replan_step", current_step)
                    setattr(session, "_replan_attempts", replan_attempts + 1)
                except Exception as e:
                    logger.warning(f"Re-planning failed: {e}")

            # If still no steps (or skipping due to throttle), fall back to reactive planning (Mode 3)
            if not session.executable_plan or len(session.executable_plan) == 0:
                logger.debug("No steps available; falling back to reactive planning (tool + args)")
                context_note_formatted = self.planner.format_context_note(session)
                decision = await self.planner.generate_full_plan(session, context_note_formatted)
                # Record reactive plan generation
                try:
                    self._record_plan_event(session, "plan_generated", {
                        "kind": "reactive",
                        "initial": False,
                        "decision": decision,
                    })
                except Exception as e:
                    logger.debug(f"Failed to record reactive plan: {e}")
                return decision
            else:
                # Successful re-plan -> reset attempts
                setattr(session, "_replan_attempts", 0)

        # Get next goal from (potentially refreshed) plan
        #TODO: redundant setting of goals
        session.active_goal = session.executable_plan.pop(0)
        logger.debug(f"Processing goal: {session.active_goal.value}")

        # Prepare context note (reusable for all modes)
        context_note_formatted = self.planner.format_context_note(session)

        # Mode 1: Completely planned (tool name + parameters)
        if session.active_goal.mcp_tool and session.active_goal.tool_args:
            logger.debug(f"Mode 1: Using completely pre-planned tool: {session.active_goal.mcp_tool}")
            return {
                "call_function": session.active_goal.mcp_tool,
                "arguments": session.active_goal.tool_args
            }
        
        # Mode 2: Partially planned (tool name only, need parameters)
        elif session.active_goal.mcp_tool and session.active_goal.tool_args is None:
            logger.debug(f"Mode 2: Using partially planned tool, generating parameters: {session.active_goal.mcp_tool}")
            return await self.planner.generate_tool_parameters(session, context_note_formatted)
        
        # Mode 3: No planning (need both tool name and parameters)
        else:
            logger.debug("Mode 3: No pre-planning, generating tool selection and parameters")
            return await self.planner.generate_full_plan(session, context_note_formatted)

    async def _act(self, decision: dict) -> str:
        fn_name = decision["call_function"]
        fn_args = decision.get("arguments", {})
        
        # Execute the tool using MCP interface
        if hasattr(self.mcp, "execute_tool"):
            return await self.mcp.execute_tool(fn_name, fn_args)
        
        tool_info = next((t for t in getattr(self.mcp, "tools_registry", []) if t["name"] == fn_name), None)
        if not tool_info:
            return f"Tool '{fn_name}' not found"
        
        tool_result = await tool_info["session"].call_tool(fn_name, fn_args)
        if hasattr(tool_result, "content") and isinstance(tool_result.content, list) and tool_result.content:
            first = tool_result.content[0]
            return getattr(first, "text", str(first))
        return str(tool_result)
    
    async def _observe(self, session: AgentSession) -> str:
        tool = session.last_decision.get("call_function") if session.last_decision else ""
        args = session.last_decision.get("arguments", {}) if session.last_decision else {}
        preconds = getattr(session.active_goal, "assumed_preconditions", []) if session.active_goal else []
        effects = getattr(session.active_goal, "assumed_effects", []) if session.active_goal else []

        version = getattr(session, "prompt_profile", {}).get("step_summary", "v2")
        spec = REGISTRY.get("step_summary", version=version)
        summary_prompt = spec.render(
            user_prompt=session.user_prompt,
            current_goal=session.active_goal.value if session.active_goal else "",
            preconditions_block=preconds,
            effects_block=effects,
            tool=tool,
            args=json.dumps(args, ensure_ascii=False),
            last_observation=session.last_observation or "",
            plan=session.executable_plan
        )

        # TODO: tun here json mode on so that I can ckeck if all preconditions are met. Initiate replanning if precondition are not met
        return await asyncio.to_thread(
            self.llm.call,
            prompt=summary_prompt,
            system_prompt="",
            json_mode=True,
        )

    def _get_plan_summary(self, session: AgentSession) -> dict:
        """Generate a summary of the hierarchical plan for API response."""
        if not session.plan or session.planning_mode != PlanningMode.HIERARCHICAL:
            return None
        
        def node_to_dict(node: Node) -> dict:
            return self._node_to_dict(node)
        
        return {
            "planning_mode": session.planning_mode.name,
            "tree_structure": node_to_dict(session.plan.root) if session.plan.root else None,
            "total_goals": len(session.plan.get_leaves()) if session.plan else 0,
            "completed_goals": session.step_index,
            "remaining_goals": len(session.executable_plan or []),
            "current_goal": {
                "value": session.active_goal.value,
                "mcp_tool": session.active_goal.mcp_tool,
                "abstraction_score": session.active_goal.abstraction_score,
                "assumed_preconditions": getattr(session.active_goal, "assumed_preconditions", None),
                "assumed_effects": getattr(session.active_goal, "assumed_effects", None),
            } if session.active_goal else None
        }

    async def loop_run(self, session: AgentSession, progress: ProgressCb | None = None):
        """Multi-step ReAct controller. Repeats plan -> act -> summarise up to max_steps or until DONE/ERROR."""
        try:
            # Store session reference for dynamic parameter resolution
            self._current_session = session
            
            # Initialize trace early so we can capture initial plan generation
            session.trace = []

            # Initialize hierarchical plan if in hierarchical mode
            if session.planning_mode == PlanningMode.HIERARCHICAL and not session.executable_plan:
                await self.init_plan(session)
            
            start(session=session)

            if not session.tools_meta:
                session.tools_meta = self.mcp.get_tools_json()

            final_observation: str = ""

            while session.state not in (AgentState.DONE, AgentState.ERROR) and session.step_index < session.max_steps:
                if progress:
                    progress("Selecting tool...")

                decision = await self._plan(session)

                # Planning-phase completion: stop before acting if planner indicates done/terminate
                if isinstance(decision, dict) and ("goal_reached" in decision or "terminate" in decision):
                    session.goal_reached = bool(decision.get("goal_reached", False))
                    session.terminate = bool(decision.get("terminate", False))
                    session.trace.append({
                        "step": session.step_index,
                        "goal": session.active_goal.value if session.active_goal else "Plan completed",
                        "plan": decision,
                        "act": None,
                        "observation": "Planning indicated completion.",
                        "remaining_goals": 0
                    })
                    session.state = AgentState.DONE
                    break

                on_planned(session, decision)

                if progress:
                    progress(f"Executing {decision['call_function']}...")
                observation = await self._act(decision)
                on_executed(session, str(observation))

                if progress:
                    progress("Summarising response...")

                # TODO: after tunring json mode on parse response properly and do checks for the effects here
                summary = await self._observe(session)
                final_observation = json_to_markdown(summary)

                try:
                    summary_json = json.loads(summary)

                except json.JSONDecodeError as e:
                    logger.error(f"JSON parsing failed: {e}")
                    logger.error(f"Raw response: {repr(summary)}")
                    raise ValueError(f"Failed to parse JSON response: {str(e)}")

                session.trace.append({
                    "step": session.step_index,
                    "goal": session.active_goal.value if session.active_goal else None,
                    "goal_abstraction": session.active_goal.abstraction_score if session.active_goal else None,
                    "assumed_preconditions": getattr(session.active_goal, "assumed_preconditions", None),
                    "assumed_effects": getattr(session.active_goal, "assumed_effects", None),
                    "plan": decision,
                    "act": observation,
                    "observation": summary_json,
                    "remaining_goals": len(session.executable_plan or [])
                })

                on_summarised(session)
                # If lifecycle sets DONE immediately but steps remain, continue planning
                if session.state == AgentState.DONE and session.step_index < session.max_steps:
                    session.state = AgentState.PLANNING

                # For hierarchical planning: if done but more goals remain, continue
                if (session.state == AgentState.DONE and 
                    session.planning_mode == PlanningMode.HIERARCHICAL and 
                    session.executable_plan and len(session.executable_plan) > 0):

                    session.state = AgentState.PLANNING

            return final_observation, session.trace, self._get_plan_summary(session)

        except Exception as e:
            on_error(session, e)
            if progress:
                progress(f"Error: {e}")
            return f"Agent error: {e}", getattr(session, "trace", []), None
        finally:
            self._current_session = None