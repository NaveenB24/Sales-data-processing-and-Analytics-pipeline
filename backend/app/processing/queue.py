"""Single-dispatcher background job queue.

Jobs run one at a time; the parallelism lives inside each job's worker pool, so
the SQLite writer stays single-threaded per job.
"""

from __future__ import annotations

import queue as _queue
import threading
import time
from collections.abc import Callable

from app.logging_config import get_logger

log = get_logger("processing.queue")

_STOP = object()


def _default_handler(job_id: str) -> None:
    # Imported lazily so `queue` stays importable without the ORM/pipeline stack.
    from app.processing import pipeline

    pipeline.process_job(job_id)


class JobQueue:
    def __init__(self, handler: Callable[[str], None] | None = None) -> None:
        self._handler = handler or _default_handler
        self._queue: _queue.Queue[object] = _queue.Queue()
        self._lock = threading.RLock()
        self._idle = threading.Condition(self._lock)
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._in_flight = 0

    # --- lifecycle -----------------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopping = False
            self._thread = threading.Thread(target=self._run, name="job-dispatcher", daemon=True)
            self._thread.start()
        log.info("queue.started")

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            thread = self._thread
            if thread is None:
                return
            self._stopping = True
        self._queue.put(_STOP)
        thread.join(timeout)
        with self._lock:
            if not thread.is_alive():
                self._thread = None
        log.info("queue.stopped")

    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    # --- producer ------------------------------------------------------
    def enqueue(self, job_id: str) -> None:
        self.start()
        self._queue.put(job_id)
        log.info("queue.enqueued", job_id=job_id, pending=self.pending())

    def pending(self) -> int:
        return self._queue.qsize()

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Block until the queue is drained and no job is in flight (test helper)."""
        deadline = time.monotonic() + timeout
        with self._idle:
            while self._queue.unfinished_tasks > 0 or self._in_flight > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._idle.wait(min(remaining, 0.05))
        return True

    # --- consumer ------------------------------------------------------
    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                self._queue.task_done()
                self._notify_idle()
                return
            job_id = str(item)
            with self._lock:
                self._in_flight += 1
            try:
                self._handler(job_id)
            except Exception as exc:  # noqa: BLE001 - one bad job must not kill the dispatcher
                log.error("queue.handler_failed", job_id=job_id, error=str(exc), exc_info=True)
            finally:
                with self._lock:
                    self._in_flight -= 1
                self._queue.task_done()
                self._notify_idle()

    def _notify_idle(self) -> None:
        with self._idle:
            self._idle.notify_all()


job_queue = JobQueue()
