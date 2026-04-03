"""
Shared pytest fixtures and helpers for the StockOS test suite.
All tests use an in-memory SQLite DB so they are isolated and repeatable.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["FLASK_ENV"] = "testing"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE", None)

import pytest
from app import create_app


# ─── App / client fixtures ──────────────────────────────────────────────────

@pytest.fixture(scope="session")
def app():
    """One app instance for the whole session (shared in-memory DB)."""
    _app = create_app("testing")
    _app.config["TESTING"] = True
    return _app


@pytest.fixture(scope="session")
def client(app):
    """Flask test client, session-scoped so auth state carries between tests."""
    return app.test_client()


@pytest.fixture(scope="session")
def tokens(client):
    """
    Returns {admin, manager, operator, buyer} tokens.
    Manager, operator and buyer are created on first use.
    """
    # Admin always exists (seeded)
    admin_tok = _login(client, "admin@stock.com", "admin123")

    extras = [
        ("Manager Teste",   "mgr@test.com",  "mgr12345",  "manager"),
        ("Operador Teste",  "op@test.com",   "op1234567", "operator"),
        ("Comprador Teste", "buy@test.com",  "buy123456", "buyer"),
    ]
    for name, email, pwd, role in extras:
        client.post(
            "/api/auth/register",
            json={"name": name, "email": email, "password": pwd, "role": role},
            headers={"Authorization": f"Bearer {admin_tok}"},
        )

    return {
        "admin":    admin_tok,
        "manager":  _login(client, "mgr@test.com",  "mgr12345"),
        "operator": _login(client, "op@test.com",   "op1234567"),
        "buyer":    _login(client, "buy@test.com",  "buy123456"),
    }


# ─── Low-level helpers (also importable from test files) ────────────────────

def _login(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return (r.get_json() or {}).get("access_token", "")


def auth(token):
    """Return Authorization header dict."""
    return {"Authorization": f"Bearer {token}"}


def get(client, path, token):
    return client.get(path, headers=auth(token))


def post(client, path, token, body=None, **kwargs):
    return client.post(path, json=body, headers=auth(token), **kwargs)


def put(client, path, token, body=None):
    return client.put(path, json=body, headers=auth(token))


def delete(client, path, token):
    return client.delete(path, headers=auth(token))
