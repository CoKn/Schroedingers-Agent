# Agent/Domain/planning/llm_planner.py
from __future__ import annotations
import asyncio
import json
from typing import Callable
from Agent.Domain.prompts.registry import REGISTRY
from Agent.Domain.agent_lifecycle import AgentSession

ProgressCb = Callable[[str], None]

class LLMPlanner:
    def __init__(self, llm, get_tool_docs: Callable[[str | None], str]):
        """
        get_tool_docs(tool_name|None) should return the docs string exactly as your current _get_tool_docs.
        """
        self.llm = llm
        self._get_tool_docs = get_tool_docs

    def _observation_history(self, session: AgentSession, N: int = 4) -> list[str]:
        return [t.get("observation") for t in (session.trace or []) if "observation" in t][-N:]

    def format_context_note(self, session: AgentSession) -> str:
        """
        Formats the reusable context note using the registry-backed prompt.
        Also appends preconditions/effects exactly like your current logic.
        """
        base = ""
        if session.step_index > 0 and session.last_observation is not None:
            prev_tool = session.last_decision.get("call_function") if session.last_decision else ""
            version = getattr(session, "prompt_profile", {}).get("context", "v1")
            spec = REGISTRY.get("context", version=version) 
            base = spec.render(
                user_prompt=session.active_goal.value if session.active_goal else "",
                step_index=session.step_index,
                prev_tool=prev_tool or "",
                last_observation=session.last_observation or "",
                observation_history=self._observation_history(session),
            )

        preconds = getattr(session.active_goal, "assumed_preconditions", []) or []
        effects  = getattr(session.active_goal, "assumed_effects", []) or []
        extra = []
        if preconds:
            extra.append("Assumed preconditions for this step:\n- " + "\n- ".join(preconds))
        if effects:
            extra.append("Target effects/outcomes for this step:\n- " + "\n- ".join(effects))
        if extra:
            base = (base + ("\n\n" if base else "")) + "\n\n".join(extra)
        return base.strip()

    async def generate_tool_parameters(self, session: AgentSession, context_note: str) -> dict:
        """Mode 2: you already know the tool, need args."""
        tool_docs = self._get_tool_docs(session.active_goal.mcp_tool)
        pre = getattr(session.active_goal, "assumed_preconditions", []) or []
        eff = getattr(session.active_goal, "assumed_effects", []) or []

        planning_spec = REGISTRY.get("planning", version="v1")
        planning_prompt = planning_spec.render(
            user_goal=session.active_goal.value if session.active_goal else "",
            tool_name=session.active_goal.mcp_tool if session.active_goal else None,
            step_index=session.step_index,
            max_steps=session.max_steps,
            preconditions=pre,
            effects=eff,
        )

        dyn_spec = REGISTRY.get("dynamic_parameters")
        sys_prompt = dyn_spec.render(context_note=context_note, tool_docs=tool_docs)

        resp = await asyncio.to_thread(
            self.llm.call,
            prompt=planning_prompt,
            system_prompt=sys_prompt,
            json_mode=dyn_spec.json_mode,
        )
        parsed = json.loads(resp)
        if "call_function" in parsed:
            parsed["call_function"] = session.active_goal.mcp_tool
        return parsed

    async def generate_full_plan(self, session: AgentSession, context_note: str) -> dict:
        """Mode 3: select tool + args."""
        tool_docs = self._get_tool_docs()
        pre = getattr(session.active_goal, "assumed_preconditions", []) or []
        eff = getattr(session.active_goal, "assumed_effects", []) or []

        planning_spec = REGISTRY.get("planning", version="v1")
        planning_prompt = planning_spec.render(
            user_goal=session.active_goal.value if session.active_goal else "",
            tool_name=None,
            step_index=session.step_index,
            max_steps=session.max_steps,
            preconditions=pre,
            effects=eff,
        )

        plan_spec = REGISTRY.get("system")
        sys_prompt = plan_spec.render(context_note=context_note, tool_docs=tool_docs)

        resp = await asyncio.to_thread(
            self.llm.call,
            prompt=planning_prompt,
            system_prompt=sys_prompt,
            json_mode=plan_spec.json_mode,
        )
        return json.loads(resp)
