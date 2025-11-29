# Agent/Domain/planning/llm_planner.py
from __future__ import annotations
import asyncio
import json
from typing import Callable
from Agent.Domain.prompts.registry import REGISTRY
from Agent.Domain.agent_lifecycle import AgentSession
from Agent.Domain.agent_prompt_config import AgentPrompts

ProgressCb = Callable[[str], None]

class LLMPlanner:
    def __init__(self, llm, get_tool_docs: Callable[[str | None], str]):
        """
        get_tool_docs(tool_name|None) should return the docs string exactly as your current _get_tool_docs.
        """
        self.llm = llm
        self._get_tool_docs = get_tool_docs

    def _observation_history(self, session: AgentSession, N: int = 5) -> list[str]:
        """Return recent raw tool results from the trace."""
        all_obs = [
            t.get("tool_result")
            for t in (session.trace or [])
            if isinstance(t, dict) and "tool_result" in t
        ]
        all_obs = [o for o in all_obs if o is not None]
        if N == -1:
            return all_obs
        return all_obs[-N:]

    
    def _facts(self, session: AgentSession) -> list[str]:
        """Aggregate per-step facts stored on the trace."""
        facts: list[str] = []
        for t in (session.trace or []):
            if not isinstance(t, dict):
                continue
            step_facts = t.get("facts")
            if isinstance(step_facts, list):
                for f in step_facts:
                    facts.append(str(f))
        return facts


    def format_context_note(self, session: AgentSession) -> str:
        """
        Formats the reusable context note using the registry-backed prompt.
        Also appends preconditions/effects exactly like your current logic.
        """
        base = ""
        if session.step_index > 0 and session.last_observation is not None:
            prev_tool = session.last_decision.get("call_function") if session.last_decision else ""

            spec = REGISTRY.get(*AgentPrompts.context)
            base = spec.render(
                user_prompt=session.active_goal.value if session.active_goal else "",
                step_index=session.step_index,
                prev_tool=prev_tool or "",
                last_observation=session.last_observation or "",
                observation_history=self._observation_history(session),
                facts=self._facts(session=session)
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
        
        planning_spec = REGISTRY.get(*AgentPrompts.planning)
        planning_prompt = planning_spec.render(
            global_goal=session.user_prompt,
            step_goal=session.active_goal.value if session.active_goal else "",
            tool_name=session.active_goal.mcp_tool if session.active_goal else None,
            step_index=session.step_index,
            max_steps=session.max_steps,
            preconditions=pre,
            effects=eff,
            enforce_required_vars=False
        )

        dyn_spec = REGISTRY.get(*AgentPrompts.dynamic_parameters)
        sys_prompt = dyn_spec.render(context_note=context_note, tool_docs=tool_docs)

        resp = await asyncio.to_thread(
            self.llm.call,
            prompt=planning_prompt,
            system_prompt=sys_prompt,
            json_mode=True,
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

        planning_spec = REGISTRY.get(*AgentPrompts.planning)
        planning_prompt = planning_spec.render(
            global_goal=session.user_prompt,
            step_goal=session.active_goal.value if session.active_goal else "",
            tool_name=None,
            step_index=session.step_index,
            max_steps=session.max_steps,
            preconditions=pre,
            effects=eff,
            enforce_required_vars=False
        )

        system_spec = REGISTRY.get(*AgentPrompts.system)
        sys_prompt = system_spec.render(context_note=context_note, tool_docs=tool_docs)

        resp = await asyncio.to_thread(
            self.llm.call,
            prompt=planning_prompt,
            system_prompt=sys_prompt,
            json_mode=True,
        )
        return json.loads(resp)
