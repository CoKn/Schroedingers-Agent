from __future__ import annotations

import asyncio
import json
from typing import Callable

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

ProgressCb = Callable[[str], None]


class AgentService:
    def __init__(self, llm: LLM, mcp):
        self.llm = llm
        self.mcp = mcp

    async def run(self, session: AgentSession, progress: ProgressCb | None = None):
        try:
            start(session)

            if not session.tools_meta:
                session.tools_meta = self.mcp.get_tools_json()

            # Plan
            if progress:
                progress("Selecting tool...")
            decision = await self._plan(session)
            on_planned(session, decision)

            # Act
            if progress:
                progress(f"Executing {decision['call_function']}...")
            observation = await self._act(decision)
            on_executed(session, observation)

            # Summarise
            if progress:
                progress("Summarising response...")
            final = await self._summarise(session)
            on_summarised(session)

            session.trace.append({"plan": decision, "act": observation, "observation": final})

            return final, session.trace

        except Exception as e:
            on_error(session, e)
            if progress:
                progress(f"Error: {e}")
            return f"Agent error: {e}", session.trace

    async def _plan(self, session: AgentSession) -> dict:
        tool_docs = "\n\n".join(
            f"{t['name']}: {t['description']}\nInput schema: {t['schema']}"
            for t in session.tools_meta
        )
        system_prompt = (
            "You are a helpful assistant. "
            "You can call one tool by returning JSON exactly in the form:\n"
            '{ "call_function": "<tool_name>", "arguments": { ... } }\n\n'
            f"Available tools:\n{tool_docs}"
        )
        resp = await asyncio.to_thread(
            self.llm.call,
            prompt=session.user_prompt,
            system_prompt=system_prompt,
            json_mode=True,
        )
        return json.loads(resp)

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
        tool = session.last_decision.get("call_function")
        args = session.last_decision.get("arguments", {})
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


    async def loop_run(self, session: AgentSession):
        while session.state != AgentState.DONE or session.state != AgentState.ERROR:
            self.run(session=session)