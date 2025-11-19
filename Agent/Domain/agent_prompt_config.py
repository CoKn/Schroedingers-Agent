from dataclasses import dataclass


@dataclass(frozen=True)
class AgentPrompts:
    goal_decomposition: tuple[str, str] = ("goal_decomposition", "v1")
    step_summary: tuple[str, str] = ("step_summary", "v3")
    planning: tuple[str, str] = ("planning", "v2")
    dynamic_parameters: tuple[str, str] = ("dynamic_parameters", "v3")
    context: tuple[str, str] = ("context", "v2")
    system: tuple[str, str] = ("system", "v1")
    goal_decomposition_replanning: tuple[str, str] = ("goal_decomposition_replanning", "v3")