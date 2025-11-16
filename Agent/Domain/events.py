from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union


class AgentEventType(str, Enum):
    # Session lifecycle
    SESSION_STARTED = "session.started"

    # Planning / replanning
    PLANNING_STARTED = "planning.started"
    REPLANNING_STARTED = "replanning.started"
    PLAN_GENERATED = "plan.generated"

    # High-level execution step lifecycle
    EXECUTION_STEP_STARTED = "execution.step.started"
    EXECUTION_STEP_COMPLETED = "execution.step.completed"

    # Step-level planning details
    STEP_GOAL_SELECTED = "step.goal_selected"
    STEP_PLAN_MODE_DECIDED = "step.plan_mode_decided"
    STEP_TOOL_PREPLANNED = "step.tool.preplanned"  # Mode 1
    STEP_TOOL_PARAMS_REQUESTED = "step.tool_params.requested"  # Mode 2
    STEP_TOOL_SELECTION_REQUESTED = "step.tool_selection.requested"  # Mode 3
    STEP_DECISION_READY = "step.decision.ready"  # final decision (tool + args)

    # Tool exe + summary
    STEP_TOOL_EXECUTED = "step.tool_execution.finished"
    STEP_SUMMARY_RECEIVED = "step.summary.received"

    # Errors
    ERROR = "error"




@dataclass(frozen=True)
class AgentEvent:
    type: AgentEventType
    data: Dict[str, Any] | None = None


Callback = Callable[[AgentEvent], Union[None, Awaitable[None]]]


class EventBus:
    """Simple async-aware event bus for the agent lifecycle.

    - Subscribers can be sync or async callables.
    - `publish` awaits async subscribers; sync ones run inline.
    - `subscribe` returns an `unsubscribe` function.
    """

    def __init__(self) -> None:
        self._subs: Dict[AgentEventType, List[Callback]] = defaultdict(list)
        self._logger = logging.getLogger(__name__)

    def subscribe(self, event_type: AgentEventType, callback: Callback) -> Callable[[], None]:
        self._subs[event_type].append(callback)

        def _unsubscribe() -> None:
            try:
                self._subs[event_type].remove(callback)
            except ValueError:
                pass

        return _unsubscribe

    async def publish(self, event: AgentEvent) -> None:
        callbacks = list(self._subs.get(event.type, []))
        for cb in callbacks:
            try:
                result = cb(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                self._logger.exception("Event subscriber failed for %s", event.type)
