"""
Unit tests — Projects & Project Needs
Covers: list, create, get, update, needs CRUD, match, role restrictions.
"""
import pytest
from tests.conftest import get, post, put, delete


@pytest.fixture(scope="module")
def project_id(client, tokens):
    r = post(client, "/api/projects/", tokens["admin"],
             {"name": "Projeto QA", "description": "Projeto de testes",
              "cost_center": "CC-QA", "status": "active"})
    assert r.status_code == 201
    return r.get_json()["id"]


@pytest.fixture(scope="module")
def project_product_id(client, tokens):
    """Product used by project needs."""
    r = post(client, "/api/products/", tokens["admin"],
             {"name": "Produto Projeto QA", "sku": "PROJ-QA-001",
              "stock": 200, "min_stock": 10})
    assert r.status_code == 201
    return r.get_json()["id"]


class TestProjects:
    def test_list_projects(self, client, tokens):
        r = get(client, "/api/projects/", tokens["admin"])
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_create_project(self, client, tokens, project_id):
        assert project_id

    def test_get_project(self, client, tokens, project_id):
        r = get(client, f"/api/projects/{project_id}", tokens["admin"])
        assert r.status_code == 200
        assert r.get_json()["name"] == "Projeto QA"

    def test_update_project(self, client, tokens, project_id):
        r = put(client, f"/api/projects/{project_id}", tokens["admin"],
                {"status": "on_hold"})
        assert r.status_code == 200

    def test_project_not_found(self, client, tokens):
        r = get(client, "/api/projects/no-such-id", tokens["admin"])
        assert r.status_code == 404

    def test_operator_cannot_create_project(self, client, tokens):
        r = post(client, "/api/projects/", tokens["operator"],
                 {"name": "Op Project", "cost_center": "CC-X"})
        assert r.status_code == 403


class TestProjectNeeds:
    def test_add_need(self, client, tokens, project_id, project_product_id):
        r = post(client, f"/api/projects/{project_id}/needs", tokens["admin"],
                 {"product_id": project_product_id, "quantity_needed": 30,
                  "observation": "Urgente"})
        assert r.status_code == 201

    def test_list_needs(self, client, tokens, project_id):
        r = get(client, f"/api/projects/{project_id}/needs", tokens["admin"])
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)
        assert len(r.get_json()) >= 1

    def test_update_need(self, client, tokens, project_id):
        needs = get(client, f"/api/projects/{project_id}/needs",
                    tokens["admin"]).get_json()
        need_id = needs[0]["id"]
        r = put(client, f"/api/projects/{project_id}/needs/{need_id}",
                tokens["admin"], {"quantity_needed": 50})
        assert r.status_code == 200

    def test_delete_need(self, client, tokens, project_id):
        # Add then delete
        r = post(client, f"/api/projects/{project_id}/needs", tokens["admin"],
                 {"product_id":
                      get(client, "/api/products/", tokens["admin"]).get_json()[0]["id"],
                  "quantity_needed": 5})
        need_id = r.get_json()["id"]
        r2 = delete(client, f"/api/projects/{project_id}/needs/{need_id}",
                    tokens["admin"])
        assert r2.status_code == 200

    def test_match_runs(self, client, tokens, project_id):
        r = post(client, f"/api/projects/{project_id}/match", tokens["admin"])
        assert r.status_code == 200
