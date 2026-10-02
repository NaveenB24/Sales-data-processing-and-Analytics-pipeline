"""Fan-out of job progress events from worker threads to WebSocket subscribers."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

MAX_QUEUE_SIZE = 256


class EventHub:
    """Publish/subscribe bridge.

    `publish()` is called from worker threads and must never raise or block;
    delivery is hopped onto the asyncio loop with `call_soon_threadsafe`.
    """

    def __init__(self, max_queue_size: int = MAX_QUEUE_SIZE) -> None:
        self._lock = threading.RLock()
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last: dict[str, dict[str, Any]] = {}
        self._max_queue_size = max_queue_size

    # --- loop binding --------------------------------------------------
    def bind_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        with self._lock:
            self._loop = loop

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    # --- subscriptions -------------------------------------------------
    def subscribe(self, job_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._max_queue_size)
        with self._lock:
            self._subscribers.setdefault(job_id, []).append(queue)
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            queues = self._subscribers.get(job_id)
            if not queues:
                return
            try:
                queues.remove(queue)
            except ValueError:
                return
            if not queues:
                self._subscribers.pop(job_id, None)

    def subscriber_count(self, job_id: str) -> int:
        with self._lock:
            return len(self._subscribers.get(job_id, ()))

    # --- publishing ----------------------------------------------------
    def publish(self, job_id: str, message: dict[str, Any]) -> None:
        try:
            with self._lock:
                self._last[job_id] = message
                loop = self._loop
                queues = list(self._subscribers.get(job_id, ()))
            if loop is None or loop.is_closed() or not queues:
                return
            for queue in queues:
                try:
                    loop.call_soon_threadsafe(self._deliver, queue, message)
                except RuntimeError:  # loop shut down between the check and the call
                    return
        except Exception:  # pragma: no cover - publishing must never break a job
            return

    @staticmethod
    def _deliver(queue: asyncio.Queue[dict[str, Any]], message: dict[str, Any]) -> None:
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            # Slow subscriber: drop the oldest event rather than block the loop.
            try:
                queue.get_nowait()
                queue.put_nowait(message)
            except Exception:
                return
        except Exception:
            return

    def last_message(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._last.get(job_id)

    def clear(self, job_id: str | None = None) -> None:
        with self._lock:
            if job_id is None:
                self._last.clear()
                self._subscribers.clear()
            else:
                self._last.pop(job_id, None)
                self._subscribers.pop(job_id, None)


hub = EventHub()
