"""In-process experiment events used by SSE and polling-compatible state."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Mapping


class ExperimentEventBus:
    def __init__(self, history_limit: int = 200) -> None:
        self._history = defaultdict(lambda: deque(maxlen=history_limit))
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

    async def publish(self, experiment_id: str, event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        event = {
            "type": event_type,
            "experiment_id": experiment_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": dict(payload),
        }
        self._history[experiment_id].append(event)
        for queue in list(self._subscribers[experiment_id]):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass
        return event

    def history(self, experiment_id: str) -> list[dict[str, Any]]:
        return list(self._history[experiment_id])

    async def stream(self, experiment_id: str) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers[experiment_id].add(queue)
        try:
            for event in self.history(experiment_id):
                yield event
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield {"type": "keepalive", "experiment_id": experiment_id, "payload": {}}
        finally:
            self._subscribers[experiment_id].discard(queue)

