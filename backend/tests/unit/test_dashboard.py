"""
Unit tests — Dashboard & Audit endpoints
"""
import pytest
from tests.conftest import get, post


class TestDashboard:
    def test_summary(self, client, tokens):
        r = get(client, "/api/dashboard/summary", tokens["admin"])
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, dict)

    def test_low_stock(self, client, tokens):
        r = get(client, "/api/dashboard/low-stock", tokens["admin"])
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_recent_movements(self, client, tokens):
        r = get(client, "/api/dashboard/recent-movements", tokens["admin"])
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_pending_needs(self, client, tokens):
        r = get(client, "/api/dashboard/pending-needs", tokens["admin"])
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_operator_can_access_dashboard(self, client, tokens):
        r = get(client, "/api/dashboard/summary", tokens["operator"])
        assert r.status_code == 200


class TestAudit:
    def test_list_audit_logs(self, client, tokens):
        r = get(client, "/api/audit/", tokens["admin"])
        assert r.status_code == 200

    def test_audit_filter_by_action(self, client, tokens):
        r = get(client, "/api/audit/?action=create", tokens["admin"])
        assert r.status_code == 200

    def test_audit_filter_by_entity(self, client, tokens):
        r = get(client, "/api/audit/?entity_type=tool", tokens["admin"])
        assert r.status_code == 200

    def test_audit_summary(self, client, tokens):
        r = get(client, "/api/audit/summary", tokens["admin"])
        assert r.status_code == 200

    def test_audit_entity_history(self, client, tokens):
        # Get any tool id to test entity history
        tools = get(client, "/api/tools/", tokens["admin"]).get_json()
        if tools:
            tid = tools[0]["id"]
            r = get(client, f"/api/audit/entity/tool/{tid}", tokens["admin"])
            assert r.status_code == 200

    def test_operator_cannot_access_audit(self, client, tokens):
        r = get(client, "/api/audit/", tokens["operator"])
        assert r.status_code == 403

    def test_buyer_cannot_access_audit(self, client, tokens):
        r = get(client, "/api/audit/", tokens["buyer"])
        assert r.status_code == 403
