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
def auth(client):
    """Signup helper returning (headers, user_dict) for a fresh user."""
    counter = {"n": 0}

    def _make(email: str | None = None, password: str = "password123", role: str = "user"):
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
