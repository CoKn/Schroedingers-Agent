from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

from Agent.Domain.prompts.context_prompt import context_prompt
from Agent.Domain.prompts.goal_decomposition_prompt import goal_decomposition_prompt
from Agent.Domain.prompts.system_prompt import system_prompt
from Agent.Domain.prompts.dynamic_parameters import dynamic_parameters_prompt

from Agent.Domain.plan import Tree, Node
from Agent.Domain.agent_state_enum import AgentState
from Agent.Domain.planning_mode_enum import PlanningMode
from Agent.Ports.Outbound.llm_interface import LLM
from Agent.Domain.agent_lifecycle import (
    AgentSession,
    init_plan,
    start,
    on_planned,
    on_executed,
    on_summarised,
    on_error,
)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ProgressCb = Callable[[str], None]


class AgentService:
    def __init__(self, llm: LLM, mcp):
        self.llm = llm
        self.mcp = mcp
    
    def _get_tool_docs(self, tool_name: str = None) -> str:
        """Get documentation for a specific tool or all tools.
        
        Args:
            tool_name: If provided, returns docs for only this tool.
                      If None, returns docs for all tools.
        """
        if tool_name:
            # Find the specific tool
            for tool in self.session.tools_meta:
                if tool['name'] == tool_name:
                    return f"{tool['name']}: {tool['description']}\nInput schema: {tool['schema']}"
            raise ValueError(f"Tool '{tool_name}' not found in available tools")
        else:
            # Return all tools
            return "\n\n".join(
                f"{t['name']}: {t['description']}\nInput schema: {t['schema']}" 
                for t in self.session.tools_meta
            )

    # hierarchical planning 
    async def init_plan(self, session: AgentSession):
        """Initialize hierarchical plan by decomposing the user goal into executable sub-goals."""
        if not session.tools_meta:
            session.tools_meta = self.mcp.get_tools_json()
            
        # 1. initial prompt is set as root of tree
        tool_docs = "\n\n".join(
                f"{t['name']}: {t['description']}\nInput schema: {t['schema']}" for t in session.tools_meta
            )
        
        # 2. run llm call to generate tree
        resp = await asyncio.to_thread(
            self.llm.call,
            prompt=f"Goal: {session.user_prompt}",
            system_prompt=goal_decomposition_prompt.format(tools=tool_docs),
            json_mode=True,
        )

         # 3. parse response to tree class
        try:
            parsed = json.loads(resp)
            # parse json to Tree class
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

        # 5. set active goal to first executable goal
        if session.executable_plan:
            session.active_goal = session.executable_plan[0]
        else:
            logger.warning("No executable goals found in plan")
            raise ValueError("Plan decomposition resulted in no executable goals")

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
        
        # Check if we have more goals to execute
        if not session.executable_plan or len(session.executable_plan) == 0:
            return {"goal_reached": True}
        
        # Get next goal from plan
        session.active_goal = session.executable_plan.pop(0)
        logger.debug(f"Processing goal: {session.active_goal.value}")

        # Prepare context note (reusable for all modes)
        context_note_formatted = self._format_context_note(session)

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
            return await self._generate_tool_parameters(session, context_note_formatted)
        
        # Mode 3: No planning (need both tool name and parameters)
        else:
            logger.debug("Mode 3: No pre-planning, generating tool selection and parameters")
            return await self._generate_full_plan(session, context_note_formatted)
    
    def _format_context_note(self, session: AgentSession) -> str:
        """Format context note for LLM prompts (reusable across planning modes)."""
        if session.step_index > 0 and session.last_observation is not None:
            prev_tool = session.last_decision.get("call_function") if session.last_decision else None
            return context_prompt.format(
                user_prompt=session.active_goal.value,
                step_index=session.step_index,
                prev_tool=prev_tool,
                last_observation=session.last_observation,
                observation_history=[t["observation"] for t in session.trace]
            )
        return
    
    async def _generate_tool_parameters(self, session: AgentSession, context_note: str) -> dict:
        """Generate parameters for a pre-selected tool (Mode 2: Partial planning)."""
        # Get documentation only for the specific tool
        tool_docs = self._get_tool_docs(session.active_goal.mcp_tool)
        
        # Create planning prompt with goal context
        planning_prompt = (
            f"User goal: {session.active_goal.value}\n"
            f"Tool to use: {session.active_goal.mcp_tool}\n"
            f"Step index: {session.step_index} of {session.max_steps}.\n"
            "Generate the appropriate parameters for this tool to achieve the goal."
        )
        
        system_prompt_formatted = dynamic_parameters_prompt.format(
            context_note=context_note,
            tool_docs=tool_docs
        )
        
        resp = await asyncio.to_thread(
            self.llm.call,
            prompt=planning_prompt,
            system_prompt=system_prompt_formatted,
            json_mode=True,
        )
        
        try:
            parsed = json.loads(resp)
            # Ensure the response uses the pre-selected tool
            if "call_function" in parsed:
                parsed["call_function"] = session.active_goal.mcp_tool
            return parsed
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing failed for parameter generation: {e}")
            logger.error(f"Raw response: {repr(resp)}")
            raise ValueError(f"Failed to parse JSON response: {str(e)}")
    
    async def _generate_full_plan(self, session: AgentSession, context_note: str) -> dict:
        """Generate both tool selection and parameters (Mode 3: No planning)."""
        # Get documentation for all tools
        tool_docs = self._get_tool_docs()
        
        planning_prompt = (
            f"User goal: {session.active_goal.value}\n"
            f"Step index: {session.step_index} of {session.max_steps}."
        )
        
        system_prompt_formatted = system_prompt.format(
            context_note=context_note,
            tool_docs=tool_docs
        )
        
        resp = await asyncio.to_thread(
            self.llm.call,
            prompt=planning_prompt,
            system_prompt=system_prompt_formatted,
            json_mode=True,
        )
        
        try:
            parsed = json.loads(resp)
            return parsed
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing failed for full planning: {e}")
            logger.error(f"Raw response: {repr(resp)}")
            raise ValueError(f"Failed to parse JSON response: {str(e)}")
        

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

    async def _summarise(self, session: AgentSession) -> str:
        tool = session.last_decision.get("call_function") if session.last_decision else ""
        args = session.last_decision.get("arguments", {}) if session.last_decision else {}
        summary_prompt = (
            f"Original query: {session.user_prompt}\n"
            f"Chosen tool: {tool} with args: {args}\n"
            f"Tool returned: {session.last_observation}\n\n"
            "Please summarise the outcome in plain text. Make sure to include all relevant information like links and ids, which might be usefull later."
        )
        return await asyncio.to_thread(
            self.llm.call,
            prompt=summary_prompt,
            system_prompt="",
            json_mode=False,
        )

    def _get_plan_summary(self, session: AgentSession) -> dict:
        """Generate a summary of the hierarchical plan for API response."""
        if not session.plan or session.planning_mode != PlanningMode.HIERARCHICAL:
            return None
        
        def node_to_dict(node: Node) -> dict:
            return {
                "value": node.value,
                "abstraction_score": node.abstraction_score,
                "status": node.status.name if node.status else None,
                "mcp_tool": node.mcp_tool,
                "tool_args": node.tool_args,
                "is_leaf": node.is_leaf(),
                "is_executable": node.is_executable(),
                "children": [node_to_dict(child) for child in (node.children or [])]
            }
        
        return {
            "planning_mode": session.planning_mode.name,
            "tree_structure": node_to_dict(session.plan.root) if session.plan.root else None,
            "total_goals": len(session.plan.get_leaves()) if session.plan else 0,
            "completed_goals": session.step_index,
            "remaining_goals": len(session.executable_plan or []),
            "current_goal": {
                "value": session.active_goal.value,
                "mcp_tool": session.active_goal.mcp_tool,
                "abstraction_score": session.active_goal.abstraction_score
            } if session.active_goal else None
        }

    async def loop_run(self, session: AgentSession, progress: ProgressCb | None = None):
        """Multi-step ReAct controller. Repeats plan -> act -> summarise up to max_steps or until DONE/ERROR."""
        try:
            # Store session reference for dynamic parameter resolution
            self._current_session = session
            
            # Initialize hierarchical plan if in hierarchical mode
            if session.planning_mode == PlanningMode.HIERARCHICAL and not session.executable_plan:
                await self.init_plan(session)
            
            start(session=session)

            if not session.tools_meta:
                session.tools_meta = self.mcp.get_tools_json()

            session.trace = []
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
                on_executed(session, observation)

                if progress:
                    progress("Summarising response...")
                summary = await self._summarise(session)
                final_observation = summary

                session.trace.append({
                    "step": session.step_index,
                    "goal": session.active_goal.value if session.active_goal else None,
                    "goal_abstraction": session.active_goal.abstraction_score if session.active_goal else None,
                    "plan": decision,
                    "act": observation,
                    "observation": summary,
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
            # Clean up session reference
            self._current_session = None