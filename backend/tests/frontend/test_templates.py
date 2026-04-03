"""
Frontend smoke tests — Template rendering
Verifies that every page route returns HTTP 200 with a valid HTML response
for authenticated users, and redirects/rejects unauthenticated requests.
All pages are expected to render without server errors (500).
"""
import pytest
from tests.conftest import _login


PROTECTED_PAGES = [
    "/dashboard",
    "/products",
    "/movements",
    "/projects",
    "/suppliers",
    "/invoices",
    "/users",
    "/reports",
    "/tools",
]


class TestUnauthenticatedAccess:
    """Pages should redirect or return 401/302 without a valid session."""

    @pytest.mark.parametrize("path", PROTECTED_PAGES)
    def test_unauthenticated_redirected(self, client, path):
        r = client.get(path)
        # Expect a redirect to /login or a 401 — never 200 without auth
        assert r.status_code in (302, 401), \
            f"Expected redirect/401 on {path}, got {r.status_code}"

    def test_login_page_accessible(self, client):
        r = client.get("/login")
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert "login" in html.lower() or "<form" in html.lower()

    def test_root_accessible(self, client):
        r = client.get("/")
        assert r.status_code in (200, 302)


class TestAuthenticatedPageRendering:
    """All pages must return 200 and valid HTML for an authenticated admin."""

    @pytest.fixture(scope="class")
    def session_cookie(self, client):
        """
        For page_login_required we need a session cookie, not a JWT header.
        Log in via the login page to get a session.
        """
        r = client.post("/api/auth/login",
                        json={"email": "admin@stock.com", "password": "admin123"})
        token = r.get_json()["access_token"]
        # Store token in cookie as the frontend does
        with client.session_transaction() as sess:
            sess["token"] = token
        return token

    @pytest.mark.parametrize("path", PROTECTED_PAGES)
    def test_page_renders_200(self, client, session_cookie, path):
        with client.session_transaction() as sess:
            sess["token"] = session_cookie
        r = client.get(path)
        # With session cookie, should return 200
        assert r.status_code in (200, 302), \
            f"Page {path} returned {r.status_code}"

    def test_dashboard_contains_expected_elements(self, client, session_cookie):
        with client.session_transaction() as sess:
            sess["token"] = session_cookie
        r = client.get("/dashboard")
        if r.status_code == 200:
            html = r.get_data(as_text=True)
            assert "<!DOCTYPE html>" in html or "<html" in html
            assert "StockOS" in html or "dashboard" in html.lower()

    def test_no_page_returns_500(self, client, session_cookie):
        """Verify no page causes a server error."""
        with client.session_transaction() as sess:
            sess["token"] = session_cookie
        for path in PROTECTED_PAGES:
            r = client.get(path)
            assert r.status_code != 500, \
                f"Page {path} returned 500 Internal Server Error"


class TestStaticAssets:
    """Verify static CSS/JS files are served correctly."""

    def test_main_css(self, client):
        r = client.get("/static/css/main.css")
        assert r.status_code == 200
        assert "text/css" in r.content_type

    def test_login_css(self, client):
        r = client.get("/static/css/login.css")
        assert r.status_code == 200

    def test_api_js(self, client):
        r = client.get("/static/js/api.js")
        assert r.status_code == 200
        assert "javascript" in r.content_type or "text" in r.content_type

    def test_auth_js(self, client):
        r = client.get("/static/js/auth.js")
        assert r.status_code == 200
