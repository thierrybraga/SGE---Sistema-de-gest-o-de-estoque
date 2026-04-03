"""
Unit tests — Stock Movements
Covers: list, entry, exit, adjustment, role restrictions, stock floor.
"""
import pytest
from tests.conftest import get, post


@pytest.fixture(scope="module")
def mov_product_id(client, tokens):
    """Create a dedicated product for movement tests."""
    r = post(client, "/api/products/", tokens["admin"],
             {"name": "Produto Mov QA", "sku": "MOV-QA-001",
              "cost_price": 5.0, "sale_price": 10.0,
              "stock": 100, "min_stock": 10, "unit": "un"})
    assert r.status_code == 201
    return r.get_json()["id"]


class TestMovements:
    def test_list_movements(self, client, tokens):
        r = get(client, "/api/movements/", tokens["admin"])
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_entry_movement(self, client, tokens, mov_product_id):
        r = post(client, "/api/movements/entry", tokens["admin"],
                 {"product_id": mov_product_id, "quantity": 50,
                  "unit_cost": 5.0, "observation": "Entrada QA"})
        assert r.status_code == 201
        mv = r.get_json()
        assert mv["type"] == "entry"
        assert mv["quantity"] == 50

    def test_exit_movement(self, client, tokens, mov_product_id):
        r = post(client, "/api/movements/exit", tokens["admin"],
                 {"product_id": mov_product_id, "quantity": 20,
                  "observation": "Saída QA"})
        assert r.status_code == 201
        assert r.get_json()["type"] == "exit"

    def test_exit_below_zero_blocked(self, client, tokens, mov_product_id):
        r = post(client, "/api/movements/exit", tokens["admin"],
                 {"product_id": mov_product_id, "quantity": 999999})
        assert r.status_code == 400

    def test_adjustment_movement(self, client, tokens, mov_product_id):
        r = post(client, "/api/movements/adjustment", tokens["admin"],
                 {"product_id": mov_product_id, "quantity": 130,
                  "observation": "Ajuste inventário"})
        assert r.status_code == 201
        assert r.get_json()["type"] == "adjustment"

    def test_list_movements_filter_by_type(self, client, tokens):
        r = get(client, "/api/movements/?type=entry", tokens["admin"])
        data = r.get_json()
        assert all(m["type"] == "entry" for m in data)

    def test_operator_can_record_movement(self, client, tokens, mov_product_id):
        r = post(client, "/api/movements/entry", tokens["operator"],
                 {"product_id": mov_product_id, "quantity": 5,
                  "observation": "Entrada by operator"})
        assert r.status_code == 201

    def test_buyer_cannot_record_movement(self, client, tokens, mov_product_id):
        r = post(client, "/api/movements/entry", tokens["buyer"],
                 {"product_id": mov_product_id, "quantity": 5})
        assert r.status_code == 403
