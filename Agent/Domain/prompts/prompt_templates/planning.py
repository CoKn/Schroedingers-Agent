from typing import Mapping, Any
from Agent.Domain.prompts.registry import register_prompt


@register_prompt("planning", kind="user", required_vars={"user_goal", "tool_name", "step_index", "max_steps", "preconditions", "effects"}, version="v1")
def planning_template(vars: Mapping[str, Any]) -> str:
    """Function-style prompt template for planning tool parameters.

    Expected keys:
    - user_goal: str
    - tool_name: str | None
    - step_index: int
    - max_steps: int
    - preconditions: list[str]
    - effects: list[str]
    - facts 

    The function deliberately keeps sections short and omits empty blocks to
    avoid unbounded prompt growth.
    """
    user_goal = vars.get("user_goal", "")
    tool_name = vars.get("tool_name") or "<unspecified>"
    step_index = vars.get("step_index", 0)
    max_steps = vars.get("max_steps", 0)
    preconds = vars.get("preconditions") or []
    effects = vars.get("effects") or []

    parts: list[str] = []
    parts.append(f"User goal: {user_goal}")
    parts.append(f"Tool to use: {tool_name}")
    parts.append(f"Step index: {step_index} of {max_steps}.")

    if preconds:
        parts.append("Assumed preconditions:")
        parts.extend(("- " + p) for p in preconds)

    if effects:
        parts.append("Desired effects/outcomes:")
        parts.extend(("- " + e) for e in effects)

    parts.append("Decide if further action is required.")
    parts.append(
        "Return EXACTLY ONE JSON object using one of these formats:"
    )
    parts.append(
        "1) If the goal is already achieved: {\"goal_reached\": true}"
    )
    parts.append(
        "2) If it's impossible/inappropriate to proceed (e.g., unmet preconditions or missing input): {\"terminate\": true, \"reason\": \"<brief>\"}"
    )
    parts.append(
        "3) Otherwise, generate the tool call parameters: {\"call_function\": \"<tool_name>\", \"arguments\": {\"param\": \"value\"}}"
    )
    parts.append("Respond with valid JSON only — no extra text.")

    return "\n".join(parts)
