"""
Unit tests — Products & Categories
Covers: list, create, get, update, delete, low-stock, categories CRUD,
        role restrictions.
"""
import pytest
from tests.conftest import get, post, put, delete


@pytest.fixture(scope="module")
def category_id(client, tokens):
    r = post(client, "/api/products/categories/", tokens["admin"],
             {"name": "TestCat", "description": "Cat for tests"})
    assert r.status_code == 201
    return r.get_json()["id"]


@pytest.fixture(scope="module")
def product_id(client, tokens, category_id):
    r = post(client, "/api/products/", tokens["admin"],
             {"name": "Produto QA", "sku": "QA-001", "cost_price": 10.0,
              "sale_price": 20.0, "stock": 50, "min_stock": 5,
              "unit": "un", "category_id": category_id})
    assert r.status_code == 201
    return r.get_json()["id"]


class TestCategories:
    def test_list_categories(self, client, tokens):
        r = get(client, "/api/products/categories/", tokens["admin"])
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_create_category(self, client, tokens):
        r = post(client, "/api/products/categories/", tokens["admin"],
                 {"name": "CatNova"})
        assert r.status_code == 201
        assert r.get_json()["name"] == "CatNova"

    def test_create_category_requires_manager(self, client, tokens):
        r = post(client, "/api/products/categories/", tokens["operator"],
                 {"name": "CatX"})
        assert r.status_code == 403

    def test_update_category(self, client, tokens, category_id):
        r = put(client, f"/api/products/categories/{category_id}",
                tokens["admin"], {"name": "TestCatUpdated"})
        assert r.status_code == 200

    def test_delete_category_with_products_blocked(self, client, tokens, category_id):
        # category has a product — should return 409
        r = delete(client, f"/api/products/categories/{category_id}", tokens["admin"])
        assert r.status_code == 409


class TestProducts:
    def test_list_products(self, client, tokens):
        r = get(client, "/api/products/", tokens["admin"])
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_create_product(self, client, tokens, product_id):
        assert product_id  # created in fixture

    def test_get_product(self, client, tokens, product_id):
        r = get(client, f"/api/products/{product_id}", tokens["admin"])
        assert r.status_code == 200
        assert r.get_json()["sku"] == "QA-001"

    def test_update_product(self, client, tokens, product_id):
        r = put(client, f"/api/products/{product_id}", tokens["admin"],
                {"sale_price": 25.0})
        assert r.status_code == 200
        assert r.get_json()["sale_price"] == 25.0

    def test_duplicate_sku_rejected(self, client, tokens, category_id):
        r = post(client, "/api/products/", tokens["admin"],
                 {"name": "Dup SKU", "sku": "QA-001",
                  "stock": 1, "category_id": category_id})
        assert r.status_code == 409

    def test_low_stock_endpoint(self, client, tokens):
        r = get(client, "/api/products/low-stock", tokens["admin"])
        assert r.status_code == 200

    def test_operator_cannot_create_product(self, client, tokens, category_id):
        r = post(client, "/api/products/", tokens["operator"],
                 {"name": "OpProd", "sku": "OP-999",
                  "stock": 1, "category_id": category_id})
        assert r.status_code == 403

    def test_delete_product_admin(self, client, tokens):
        # Create a standalone product just for deletion
        r = post(client, "/api/products/", tokens["admin"],
                 {"name": "ToDelete", "sku": "DEL-001", "stock": 0})
        pid = r.get_json()["id"]
        r2 = delete(client, f"/api/products/{pid}", tokens["admin"])
        assert r2.status_code == 200

    def test_get_nonexistent_product(self, client, tokens):
        r = get(client, "/api/products/nonexistent-id", tokens["admin"])
        assert r.status_code == 404
