"""WebSocket progress channel."""

from __future__ import annotations

from tests.conftest import SAMPLE_CSV


def _token(headers: dict) -> str:
    return headers["Authorization"].split(" ", 1)[1]


def test_websocket_rejects_missing_or_bad_token(client, auth, upload_sample):
    headers, _ = auth()
    job = upload_sample(headers)

    for query in ("", "?token=garbage"):
        try:
            with client.websocket_connect(f"/ws/jobs/{job['id']}{query}"):
                raise AssertionError("connection should have been refused")
        except Exception as exc:  # starlette raises WebSocketDisconnect on a 4401 close
            assert "should have been refused" not in str(exc)


def test_websocket_rejects_another_users_job(client, auth, upload_sample):
    alice, _ = auth(email="ws-a@example.com")
    bob, _ = auth(email="ws-b@example.com")
    job = upload_sample(alice)
    try:
        with client.websocket_connect(f"/ws/jobs/{job['id']}?token={_token(bob)}"):
            raise AssertionError("connection should have been refused")
    except Exception as exc:
        assert "should have been refused" not in str(exc)


def test_websocket_sends_initial_status(client, auth, upload_sample):
    headers, _ = auth()
    job = upload_sample(headers)
    with client.websocket_connect(f"/ws/jobs/{job['id']}?token={_token(headers)}") as ws:
        message = ws.receive_json()
        assert message["type"] == "status"
        assert message["payload"]["job_id"] == job["id"]
        assert message["payload"]["status"] == "completed"
        assert message["payload"]["percent"] == 100.0


def test_websocket_streams_progress_until_completion(client, auth):
    headers, _ = auth()
    job = client.post(
        "/api/jobs/upload",
        headers=headers,
        files={"file": ("live.csv", SAMPLE_CSV.encode(), "text/csv")},
        data={"auto_process": "false"},
    ).json()

    with client.websocket_connect(f"/ws/jobs/{job['id']}?token={_token(headers)}") as ws:
        assert ws.receive_json()["type"] == "status"
        client.post(f"/api/jobs/{job['id']}/process", headers=headers)

        seen = []
        for _ in range(40):
            message = ws.receive_json()
            if message["type"] == "ping":
                continue
            seen.append(message["type"])
            if message["type"] in ("completed", "failed"):
                final = message
                break
        else:  # pragma: no cover - would mean the pipeline never finished
            raise AssertionError(f"no terminal event, saw {seen}")

    assert final["type"] == "completed"
    assert final["payload"]["valid_rows"] == 3
    assert final["payload"]["invalid_rows"] == 3
    assert final["payload"]["duplicate_rows"] == 1
