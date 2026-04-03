"""
Unit tests — Authentication & User Management
Covers: login, register, /me GET/PUT, user list, activate/deactivate,
        role listing, user activity, logout, role restrictions.
"""
import pytest
from tests.conftest import auth, get, post, put, _login


class TestLogin:
    def test_login_success(self, client):
        r = client.post("/api/auth/login",
                        json={"email": "admin@stock.com", "password": "admin123"})
        assert r.status_code == 200
        data = r.get_json()
        assert "access_token" in data
        assert data["user"]["role"] == "admin"

    def test_login_wrong_password(self, client):
        r = client.post("/api/auth/login",
                        json={"email": "admin@stock.com", "password": "wrong"})
        assert r.status_code == 401

    def test_login_unknown_email(self, client):
        r = client.post("/api/auth/login",
                        json={"email": "nobody@x.com", "password": "x"})
        assert r.status_code == 401

    def test_login_missing_fields(self, client):
        r = client.post("/api/auth/login", json={"email": "admin@stock.com"})
        assert r.status_code == 400

    def test_no_token_returns_401(self, client):
        r = client.get("/api/auth/me")
        assert r.status_code == 401


class TestRegister:
    def test_register_new_user(self, client, tokens):
        r = post(client, "/api/auth/register", tokens["admin"],
                 {"name": "Novo User", "email": "new_reg@test.com",
                  "password": "pass12345", "role": "operator"})
        assert r.status_code in (200, 201)
        assert r.get_json()["email"] == "new_reg@test.com"

    def test_register_duplicate_email(self, client, tokens):
        body = {"name": "Dup", "email": "admin@stock.com",
                "password": "pass12345", "role": "operator"}
        r = post(client, "/api/auth/register", tokens["admin"], body)
        assert r.status_code == 409

    def test_register_requires_admin_or_manager(self, client, tokens):
        r = post(client, "/api/auth/register", tokens["operator"],
                 {"name": "X", "email": "x@x.com",
                  "password": "pass12345", "role": "operator"})
        assert r.status_code == 403

    def test_register_weak_password(self, client, tokens):
        r = post(client, "/api/auth/register", tokens["admin"],
                 {"name": "X", "email": "weak@test.com",
                  "password": "123", "role": "operator"})
        assert r.status_code == 400


class TestMe:
    def test_me_returns_current_user(self, client, tokens):
        r = get(client, "/api/auth/me", tokens["admin"])
        assert r.status_code == 200
        u = r.get_json()
        assert u["email"] == "admin@stock.com"
        assert "password_hash" not in u

    def test_me_update_name(self, client, tokens):
        r = put(client, "/api/auth/me", tokens["operator"],
                {"name": "Operador Atualizado"})
        assert r.status_code == 200

    def test_me_update_password(self, client, tokens):
        # set a new password then revert so other tests still work
        tok = tokens["operator"]
        r = put(client, "/api/auth/me", tok,
                {"current_password": "op1234567", "new_password": "op1234567NEW"})
        assert r.status_code == 200
        # revert
        new_tok = _login(client, "op@test.com", "op1234567NEW")
        put(client, "/api/auth/me", new_tok,
            {"current_password": "op1234567NEW", "new_password": "op1234567"})


class TestUserManagement:
    def test_list_users_admin(self, client, tokens):
        r = get(client, "/api/auth/users", tokens["admin"])
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)
        assert len(r.get_json()) >= 1

    def test_list_users_forbidden_for_operator(self, client, tokens):
        r = get(client, "/api/auth/users", tokens["operator"])
        assert r.status_code == 403

    def test_get_user_by_id(self, client, tokens):
        users = get(client, "/api/auth/users", tokens["admin"]).get_json()
        uid = users[0]["id"]
        r = get(client, f"/api/auth/users/{uid}", tokens["admin"])
        assert r.status_code == 200

    def test_deactivate_and_activate_user(self, client, tokens):
        # Create a temporary user
        r = post(client, "/api/auth/register", tokens["admin"],
                 {"name": "Temp", "email": "temp_deact@test.com",
                  "password": "pass12345", "role": "operator"})
        uid = r.get_json()["id"]
        r2 = post(client, f"/api/auth/users/{uid}/deactivate", tokens["admin"])
        assert r2.status_code == 200
        r3 = post(client, f"/api/auth/users/{uid}/activate", tokens["admin"])
        assert r3.status_code == 200

    def test_list_roles(self, client, tokens):
        r = get(client, "/api/auth/roles", tokens["admin"])
        assert r.status_code == 200
        roles = r.get_json()
        assert isinstance(roles, list)
        assert "admin" in [ro if isinstance(ro, str) else ro.get("id", "") for ro in roles]

    def test_logout(self, client, tokens):
        r = post(client, "/api/auth/logout", tokens["operator"])
        assert r.status_code == 200
