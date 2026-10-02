"""Authentication, authorization and tenant-isolation behaviour."""

from __future__ import annotations

import pytest

from app.security import create_access_token


def test_signup_returns_token_and_user(client, seed_bootstrap_admin):
    seed_bootstrap_admin()
    resp = client.post("/api/auth/signup", json={"email": "Alice@Example.com", "password": "password123"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["role"] == "user"


def test_first_account_becomes_admin(client):
    resp = client.post("/api/auth/signup", json={"email": "owner@example.com", "password": "password123"})
    assert resp.json()["user"]["role"] == "admin"
    second = client.post("/api/auth/signup", json={"email": "member@example.com", "password": "password123"})
    assert second.json()["user"]["role"] == "user"


def test_password_is_hashed_not_stored_plaintext(client, db, seed_bootstrap_admin):
    seed_bootstrap_admin()
    client.post("/api/auth/signup", json={"email": "bob@example.com", "password": "password123"})
    from app.models import User

    user = db.query(User).filter(User.email == "bob@example.com").one()
    assert user.password_hash != "password123"
    assert user.password_hash.startswith("$2")


def test_duplicate_email_rejected(client, auth):
    auth(email="dup@example.com")
    resp = client.post("/api/auth/signup", json={"email": "dup@example.com", "password": "password123"})
    assert resp.status_code == 409


@pytest.mark.parametrize("password", ["short", "1234567"])
def test_short_password_rejected(client, password, seed_bootstrap_admin):
    seed_bootstrap_admin()
    resp = client.post("/api/auth/signup", json={"email": "weak@example.com", "password": password})
    assert resp.status_code == 422


def test_login_success_and_failure(client, auth):
    _headers, user = auth(email="carol@example.com", password="password123")
    ok = client.post("/api/auth/login", json={"email": "carol@example.com", "password": "password123"})
    assert ok.status_code == 200
    assert ok.json()["user"]["id"] == user["id"]

    bad = client.post("/api/auth/login", json={"email": "carol@example.com", "password": "wrong-password"})
    assert bad.status_code == 401
    assert "detail" in bad.json()

    missing = client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "password123"})
    assert missing.status_code == 401


def test_me_requires_a_valid_token(client, auth):
    headers, user = auth()
    assert client.get("/api/auth/me", headers=headers).json()["id"] == user["id"]
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_expired_token_rejected(client, auth):
    _headers, user = auth()
    expired = create_access_token(subject=user["id"], expires_minutes=-5)
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


def test_token_for_deleted_user_rejected(client, db, auth):
    _headers, user = auth()
    from app.models import User

    db.delete(db.get(User, user["id"]))
    db.commit()
    token = create_access_token(subject=user["id"])
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_non_admin_blocked_from_admin_routes(client, auth):
    headers, _ = auth()
    assert client.get("/api/admin/users", headers=headers).status_code == 403
    assert client.get("/api/admin/jobs", headers=headers).status_code == 403


def test_admin_can_list_users_and_jobs(client, auth):
    admin_headers, _ = auth(email="root@example.com", role="admin")
    auth(email="someone@example.com")
    users = client.get("/api/admin/users", headers=admin_headers)
    assert users.status_code == 200
    emails = {u["email"] for u in users.json()}
    assert {"root@example.com", "someone@example.com"} <= emails
    assert client.get("/api/admin/jobs", headers=admin_headers).status_code == 200


def test_health_endpoint_is_public(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["db"] == "ok"


def test_responses_carry_correlation_id(client):
    resp = client.get("/api/health")
    assert resp.headers.get("X-Correlation-ID")
