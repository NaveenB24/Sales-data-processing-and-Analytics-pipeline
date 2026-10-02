"""WebSocket channel streaming live job progress to the dashboard."""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.db import SessionLocal
from app.logging_config import get_logger
from app.models import Job, User
from app.processing.events import hub
from app.security import TokenError, decode_access_token

router = APIRouter(tags=["realtime"])
log = get_logger("ws")

HEARTBEAT_SECONDS = 20.0


def _authorize(token: str | None, job_id: str) -> Job | None:
    """Resolve the token and confirm the caller may watch this job."""
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except TokenError:
        return None
    with SessionLocal() as db:
        user = db.get(User, payload.get("sub") or "")
        if user is None:
            return None
        job = db.get(Job, job_id)
        if job is None or (job.user_id != user.id and user.role != "admin"):
            return None
        db.expunge(job)
        return job


@router.websocket("/ws/jobs/{job_id}")
async def job_progress(websocket: WebSocket, job_id: str, token: str | None = Query(default=None)) -> None:
    # Browsers cannot set Authorization headers on a WebSocket handshake, so the
    # JWT travels as a query parameter and is validated before accepting.
    job = await asyncio.to_thread(_authorize, token, job_id)
    if job is None:
        await websocket.close(code=4401, reason="Unauthorized")
        return

    await websocket.accept()
    hub.bind_loop(asyncio.get_running_loop())
    queue = hub.subscribe(job_id)

    # Send the current state immediately so a late subscriber is never blank.
    await websocket.send_json(
        {
            "type": "status",
            "payload": {
                "job_id": job.id,
                "status": job.status,
                "total_rows": job.total_rows,
                "processed_rows": job.processed_rows,
                "valid_rows": job.valid_rows,
                "invalid_rows": job.invalid_rows,
                "duplicate_rows": job.duplicate_rows,
                "percent": job.percent,
            },
        }
    )

    try:
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping", "payload": {}})
                continue
            await websocket.send_json(message)
            if message.get("type") in ("completed", "failed"):
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover - transport level failures
        log.warning("ws.error", job_id=job_id, error=str(exc))
    finally:
        hub.unsubscribe(job_id, queue)
        if websocket.client_state is WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await websocket.close()
