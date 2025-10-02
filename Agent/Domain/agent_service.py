from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

from Agent.Domain.prompts.context_prompt import context_prompt
from Agent.Domain.prompts.goal_decomposition_prompt import goal_decomposition_prompt
from Agent.Domain.prompts.system_prompt import system_prompt

from Agent.Domain.agent_state_enum import AgentState
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
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ProgressCb = Callable[[str], None]


class AgentService:
    def __init__(self, llm: LLM, mcp):
        self.llm = llm
        self.mcp = mcp

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
        tool_docs = "\n\n".join(
            f"{t['name']}: {t['description']}\nInput schema: {t['schema']}" for t in session.tools_meta
        )

        context_note_formated = ""
        if session.step_index > 0 and session.last_observation is not None:
            prev_tool = session.last_decision.get("call_function") if session.last_decision else None

            context_note_formated = context_prompt.format(
                user_prompt=session.user_prompt,
                step_index=session.step_index,
                prev_tool=prev_tool,
                last_observation=session.last_observation
            )

        system_prompt_formated = system_prompt.format(
            context_note=context_note_formated,
            tool_docs=tool_docs
        )

        planning_prompt = (
            f"User goal: {session.user_prompt}\n"
            f"Step index: {session.step_index} of {session.max_steps}."
        )

        resp = await asyncio.to_thread(
            self.llm.call,
            prompt=planning_prompt,
            system_prompt=system_prompt_formated,
            json_mode=True,
        )

        # logger.warning(f"LLM Response: {resp}")
        try:
            parsed = json.loads(resp)
            # logger.warning(f"JSON parsed successfully: {parsed}")
            return parsed
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing failed: {e}")
            logger.error(f"Raw response: {repr(resp)}")
            raise

    async def _act(self, decision: dict) -> str:
        fn_name = decision["call_function"]
        fn_args = decision.get("arguments", {})
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
            "Please summarise the outcome in plain text."
        )
        return await asyncio.to_thread(
            self.llm.call,
            prompt=summary_prompt,
            system_prompt="",
            json_mode=False,
        )

    async def loop_run(self, session: AgentSession, progress: ProgressCb | None = None):
        """Multi-step ReAct controller. Repeats planc -> act -> summarise up to max_steps or until DONE/ERROR."""
        try:
            start(session)

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
                        "plan": decision,
                        "act": None,
                        "observation": "Planning indicated completion.",
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
                    "plan": decision,
                    "act": observation,
                    "observation": summary,
                })

                on_summarised(session)
                # If lifecycle sets DONE immediately but steps remain, continue planning
                if session.state == AgentState.DONE and session.step_index < session.max_steps:
                    session.state = AgentState.PLANNING

            return final_observation, session.trace

        except Exception as e:
            on_error(session, e)
            if progress:
                progress(f"Error: {e}")
            return f"Agent error: {e}", getattr(session, "trace", [])