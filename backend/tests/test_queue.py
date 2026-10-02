"""Background dispatcher queue behaviour."""

from __future__ import annotations

import threading
import time

from app.processing.queue import JobQueue, job_queue


def test_enqueue_runs_the_handler():
    seen: list[str] = []
    q = JobQueue(handler=seen.append)
    try:
        q.enqueue("job-1")
        q.enqueue("job-2")
        assert q.wait_idle(timeout=5.0) is True
        assert seen == ["job-1", "job-2"]
    finally:
        q.stop()


def test_start_is_idempotent_and_reports_running():
    q = JobQueue(handler=lambda _job_id: None)
    try:
        q.start()
        q.start()
        assert q.is_running() is True
        threads = [t for t in threading.enumerate() if t.name == "job-dispatcher"]
        assert len([t for t in threads if t.is_alive()]) >= 1
    finally:
        q.stop()
    assert q.is_running() is False


def test_pending_reflects_queued_work():
    gate = threading.Event()
    q = JobQueue(handler=lambda _job_id: gate.wait(5.0))
    try:
        q.enqueue("slow")
        q.enqueue("next-1")
        q.enqueue("next-2")
        time.sleep(0.05)
        assert q.pending() >= 1
        gate.set()
        assert q.wait_idle(timeout=5.0) is True
        assert q.pending() == 0
    finally:
        gate.set()
        q.stop()


def test_wait_idle_times_out_while_busy():
    gate = threading.Event()
    q = JobQueue(handler=lambda _job_id: gate.wait(5.0))
    try:
        q.enqueue("blocking")
        assert q.wait_idle(timeout=0.2) is False
    finally:
        gate.set()
        q.stop()


def test_raising_handler_does_not_kill_the_dispatcher():
    seen: list[str] = []

    def handler(job_id: str) -> None:
        seen.append(job_id)
        if job_id == "bad":
            raise RuntimeError("handler exploded")

    q = JobQueue(handler=handler)
    try:
        q.enqueue("bad")
        q.enqueue("good")
        assert q.wait_idle(timeout=5.0) is True
        assert seen == ["bad", "good"]
        assert q.is_running() is True
    finally:
        q.stop()


def test_stop_is_safe_when_never_started():
    JobQueue(handler=lambda _job_id: None).stop()


def test_module_singleton_defaults_to_the_pipeline():
    from app.processing import pipeline

    assert job_queue.is_running() is False
    job_queue.start()
    try:
        assert job_queue.is_running() is True
        # the default handler drives the real pipeline; an unknown id is a no-op
        job_queue.enqueue("does-not-exist")
        assert job_queue.wait_idle(timeout=10.0) is True
        assert pipeline.process_job is not None
    finally:
        job_queue.stop()
