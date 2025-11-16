from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, AsyncIterator, Optional, Union


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


@dataclass
class AgentEvent:
    type: AgentEventType
    data: Dict[str, Any]


class EventBus:
    def __init__(self) -> None:
        # per-event-type subscriber lists; None = wildcard subscribers
        self._subscribers: Dict[Optional[AgentEventType], List[Callable[[AgentEvent], Awaitable[None]]]] = {}
        self._lock = asyncio.Lock()

    def subscribe(
        self,
        event_type: AgentEventType | None,
        callback: Callable[[AgentEvent], Awaitable[None]],
    ) -> None:
        """
        Register a callback for a given event_type.
        If event_type is None, the callback receives *all* events.
        """
        self._subscribers.setdefault(event_type, []).append(callback)

    async def publish(self, event: AgentEvent) -> None:
        """
        Publish an event to all subscribers for that type + wildcard subscribers.
        """
        async with self._lock:
            callbacks = list(self._subscribers.get(event.type, []))
            callbacks += self._subscribers.get(None, [])

        for cb in callbacks:
            # assume async callbacks; if you support sync too, check and wrap
            await cb(event)

    async def stream(
        self,
        *event_types: AgentEventType,
    ) -> AsyncIterator[AgentEvent]:
        """
        Async iterator that yields events from this EventBus.

        Usage:
            async for event in bus.stream():
                ...

        If event_types is empty: subscribe to ALL events.
        If event_types given: subscribe only to those.
        """
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue()

        async def _enqueue(event: AgentEvent) -> None:
            await queue.put(event)

        # subscribe our internal callback
        if event_types:
            for et in event_types:
                self.subscribe(et, _enqueue)
        else:
            # wildcard subscriber
            self.subscribe(None, _enqueue)

        try:
            while True:
                ev = await queue.get()
                yield ev
        finally:
            ...