"""Test harness: isolated SQLite file per session, app factory, auth helpers."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Settings are read at import time, so redirect storage before the app loads.
_TMP = Path(tempfile.mkdtemp(prefix="sdp-tests-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP / 'test.db'}")
os.environ.setdefault("UPLOAD_DIR", str(_TMP / "uploads"))
os.environ.setdefault("LOG_DIR", str(_TMP / "logs"))
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ROW_PROCESSING_DELAY_MS", "1")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine, SessionLocal  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_tables(_create_schema):
    """Each test starts from an empty database."""
    yield
    from app import models

    with SessionLocal() as db:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def seed_bootstrap_admin():
    """The product promotes the first account to admin; tests that want plain
    users seed a throwaway owner first so signups behave like normal users."""

    def _seed() -> None:
        from app.models import User
        from app.security import hash_password

        with SessionLocal() as s:
            if s.query(User).count() == 0:
                s.add(
                    User(
                        email="bootstrap@example.com",
                        password_hash=hash_password("bootstrap-password"),
                        role="admin",
                    )
                )
                s.commit()

    return _seed


@pytest.fixture
def auth(client, seed_bootstrap_admin):
    """Signup helper returning (headers, user_dict) for a fresh user."""
    counter = {"n": 0}

    def _make(email: str | None = None, password: str = "password123", role: str = "user"):
        seed_bootstrap_admin()
        counter["n"] += 1
        email = email or f"user{counter['n']}@example.com"
        resp = client.post("/api/auth/signup", json={"email": email, "password": password})
        assert resp.status_code == 201, resp.text
        data = resp.json()
        if role == "admin":
            from app.models import User

            with SessionLocal() as s:
                u = s.get(User, data["user"]["id"])
                u.role = "admin"
                s.commit()
            resp = client.post("/api/auth/login", json={"email": email, "password": password})
            data = resp.json()
        return {"Authorization": f"Bearer {data['access_token']}"}, data["user"]

    return _make


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.deps import upload_limiter

    upload_limiter.reset()
    yield
    upload_limiter.reset()


SAMPLE_CSV = (
    "transaction_id,region,product_category,quantity,unit_price,discount_percent,transaction_date\n"
    "TXN-1001,North,Electronics,3,499.99,10,2025-01-15\n"
    "TXN-1002,South,Groceries,12,15.50,0,2025-01-15\n"
    "TXN-1003,East,Electronics,-2,299.00,5,2025-01-16\n"
    "TXN-1004,West,Apparel,5,49.99,20,2025-01-16\n"
    "TXN-1005,North,Electronics,3,499.99,10,2025-01-15\n"
    "TXN-1006,South,Groceries,7,abc,0,2025-01-17\n"
    "TXN-1007,East,Apparel,1,89.99,,2099-01-01\n"
)


@pytest.fixture
def upload_sample(client):
    """Upload the brief's sample file and wait for processing to finish."""

    def _upload(headers: dict, content: str = SAMPLE_CSV, filename: str = "sample.csv", wait: bool = True):
        resp = client.post(
            "/api/jobs/upload",
            headers=headers,
            files={"file": (filename, content.encode("utf-8"), "text/csv")},
            data={"auto_process": "true"},
        )
        assert resp.status_code == 201, resp.text
        job = resp.json()
        if wait:
            from app.processing.queue import job_queue

            assert job_queue.wait_idle(timeout=30.0), "job queue did not drain"
            job = client.get(f"/api/jobs/{job['id']}", headers=headers).json()
        return job

    return _upload
