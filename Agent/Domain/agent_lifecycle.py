from Agent.Domain.agent_state_enum import AgentState
from pydantic import BaseModel
from typing import Optional, List


class AgentSession(BaseModel):
    user_prompt: str
    state: AgentState = AgentState.PLANNING
    max_steps: int = 3
    step_index: int = 0
    tools_meta: list[dict] = []
    last_decision: Optional[dict] = None
    last_observation: Optional[str] = None
    trace: List[dict] = []


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
    # Continue planning until max_steps reached
    if session.step_index < session.max_steps:
        session.state = AgentState.PLANNING
    else:
        session.state = AgentState.DONE
    return session


def on_error(session: AgentSession, _: Exception | str) -> AgentSession:
    session.state = AgentState.ERROR
    return session

