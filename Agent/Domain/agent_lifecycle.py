from Agent.Domain.agent_state_enum import AgentState
from Agent.Domain.planning_mode_enum import PlanningMode
from Agent.Domain.plan import Tree, Node
from pydantic import BaseModel, ConfigDict
from typing import Optional, List


class AgentSession(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    user_prompt: str
    state: AgentState = AgentState.PLANNING
    max_steps: int = 3
    step_index: int = 0
    tools_meta: list[dict] = []
    last_decision: Optional[dict] = None
    last_observation: Optional[str] = None
    trace: List[dict] = []
    terminate: bool = False
    goal_reached: bool = False
    planning_mode: PlanningMode = PlanningMode.HIERARCHICAL
    plan: Optional[Tree] = None
    executable_plan: Optional[List[Node]] = None
    active_goal: Optional[Node] = None


def init_plan(session: AgentSession) -> AgentSession:
    session.state = AgentState.INIT
    return session


def start(session: AgentSession) -> AgentSession:
    session.state = AgentState.PLANNING
    session.step_index = 0
    return session


def on_planned(session: AgentSession, decision: dict) -> AgentSession:
    session.last_decision = decision
    session.state = AgentState.EXECUTING
    return session


def on_executed(session: AgentSession, observation: str) -> AgentSession:
    session.last_observation = observation
    session.state = AgentState.SUMMARISING
    return session


def on_summarised(session: AgentSession) -> AgentSession:
    session.step_index += 1
    if session.step_index < session.max_steps:
        session.state = AgentState.PLANNING
    else:
        session.state = AgentState.DONE
    return session


def on_error(session: AgentSession, _: Exception | str) -> AgentSession:
    session.state = AgentState.ERROR
    return session