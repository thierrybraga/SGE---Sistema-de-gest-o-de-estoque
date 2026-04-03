"""
Unit tests — Suppliers, Product Links & Quotations
Covers: list, create, get, update, activate/deactivate, summary,
        product-link CRUD, quotation lifecycle, CNPJ validation.
"""
import pytest
from tests.conftest import get, post, put, delete


@pytest.fixture(scope="module")
def supplier_id(client, tokens):
    r = post(client, "/api/suppliers/", tokens["admin"],
             {"name": "Fornecedor QA",
              "cnpj": "11.222.333/0001-81",   # valid CNPJ
              "email": "qa@fornecedor.com",
              "phone": "(11) 99999-0000"})
    assert r.status_code == 201, r.get_data(as_text=True)
    return r.get_json()["id"]


@pytest.fixture(scope="module")
def link_product_id(client, tokens):
    r = post(client, "/api/products/", tokens["admin"],
             {"name": "Produto Link QA", "sku": "LNK-QA-001", "stock": 0})
    assert r.status_code == 201
    return r.get_json()["id"]


@pytest.fixture(scope="module")
def link_id(client, tokens, supplier_id, link_product_id):
    r = post(client, "/api/suppliers/product-link", tokens["admin"],
             {"supplier_id": supplier_id, "product_id": link_product_id,
              "avg_price": 15.0, "lead_time": 5, "priority": 1})
    assert r.status_code == 201
    return r.get_json()["id"]


@pytest.fixture(scope="module")
def quot_product_id(client, tokens):
    r = post(client, "/api/products/", tokens["admin"],
             {"name": "Produto Cotacao QA", "sku": "COT-QA-001", "stock": 0})
    assert r.status_code == 201
    return r.get_json()["id"]


class TestSuppliers:
    def test_list_suppliers(self, client, tokens):
        r = get(client, "/api/suppliers/", tokens["admin"])
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_create_supplier(self, client, tokens, supplier_id):
        assert supplier_id

    def test_get_supplier(self, client, tokens, supplier_id):
        r = get(client, f"/api/suppliers/{supplier_id}", tokens["admin"])
        assert r.status_code == 200
        assert r.get_json()["name"] == "Fornecedor QA"

    def test_update_supplier(self, client, tokens, supplier_id):
        r = put(client, f"/api/suppliers/{supplier_id}", tokens["admin"],
                {"phone": "(11) 98888-0000"})
        assert r.status_code == 200

    def test_invalid_cnpj_rejected(self, client, tokens):
        r = post(client, "/api/suppliers/", tokens["admin"],
                 {"name": "Bad CNPJ", "cnpj": "00.000.000/0000-00"})
        assert r.status_code == 400

    def test_duplicate_cnpj_rejected(self, client, tokens, supplier_id):
        r = post(client, "/api/suppliers/", tokens["admin"],
                 {"name": "Dup CNPJ", "cnpj": "11.222.333/0001-81"})
        assert r.status_code == 409

    def test_deactivate_supplier(self, client, tokens, supplier_id):
        r = post(client, f"/api/suppliers/{supplier_id}/deactivate",
                 tokens["admin"])
        assert r.status_code == 200

    def test_activate_supplier(self, client, tokens, supplier_id):
        r = post(client, f"/api/suppliers/{supplier_id}/activate",
                 tokens["admin"])
        assert r.status_code == 200

    def test_supplier_summary(self, client, tokens, supplier_id):
        r = get(client, f"/api/suppliers/{supplier_id}/summary", tokens["admin"])
        assert r.status_code == 200
        data = r.get_json()
        assert "supplier" in data
        assert "stats" in data

    def test_buyer_cannot_create_supplier(self, client, tokens):
        r = post(client, "/api/suppliers/", tokens["buyer"],
                 {"name": "Buyer Sup"})
        assert r.status_code == 403


class TestProductLinks:
    def test_create_link(self, client, tokens, link_id):
        assert link_id

    def test_update_link(self, client, tokens, link_id):
        r = put(client, f"/api/suppliers/product-link/{link_id}",
                tokens["admin"], {"avg_price": 18.0})
        assert r.status_code == 200

    def test_get_product_suppliers(self, client, tokens, link_product_id):
        r = get(client, f"/api/suppliers/product/{link_product_id}",
                tokens["admin"])
        assert r.status_code == 200

    def test_delete_link(self, client, tokens, supplier_id, link_product_id):
        # Create a second link to delete safely
        rp = post(client, "/api/products/", tokens["admin"],
                  {"name": "Prod Del Link", "sku": "DEL-LNK-QA", "stock": 0})
        pid2 = rp.get_json()["id"]
        rl = post(client, "/api/suppliers/product-link", tokens["admin"],
                  {"supplier_id": supplier_id, "product_id": pid2,
                   "avg_price": 5.0, "lead_time": 3, "priority": 2})
        lid2 = rl.get_json()["id"]
        r = delete(client, f"/api/suppliers/product-link/{lid2}", tokens["admin"])
        assert r.status_code == 200


class TestQuotations:
    def test_create_quotation(self, client, tokens, supplier_id, quot_product_id):
        r = post(client, "/api/suppliers/quotations/", tokens["admin"],
                 {"product_id": quot_product_id, "quantity": 50,
                  "supplier_ids": [supplier_id], "notes": "Cotação QA"})
        assert r.status_code == 201

    def test_list_quotations(self, client, tokens):
        r = get(client, "/api/suppliers/quotations/", tokens["admin"])
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_list_quotations_filter_by_status(self, client, tokens):
        r = get(client, "/api/suppliers/quotations/?status=open", tokens["admin"])
        assert r.status_code == 200
        for q in r.get_json():
            assert q["status"] == "open"

    def test_update_quotation_item_price(self, client, tokens,
                                         supplier_id, quot_product_id):
        quots = get(client, "/api/suppliers/quotations/", tokens["admin"]).get_json()
        open_q = next((q for q in quots if q["status"] == "open"), None)
        if open_q:
            items = open_q.get("items") or []
            if items:
                item_id = items[0]["id"]
                r = put(client, f"/api/suppliers/quotation-items/{item_id}",
                        tokens["buyer"], {"unit_price": 12.5, "lead_time": 4})
                assert r.status_code == 200

    def test_approve_quotation(self, client, tokens, supplier_id, quot_product_id):
        # Create a fresh quotation to approve
        r = post(client, "/api/suppliers/quotations/", tokens["admin"],
                 {"product_id": quot_product_id, "quantity": 10,
                  "supplier_ids": [supplier_id]})
        quot_id = r.get_json()["id"]
        items = r.get_json().get("items") or \
                get(client, "/api/suppliers/quotations/",
                    tokens["admin"]).get_json()[-1].get("items", [])
        if items:
            put(client, f"/api/suppliers/quotation-items/{items[0]['id']}",
                tokens["buyer"], {"unit_price": 10.0})
        ra = post(client, f"/api/suppliers/quotations/{quot_id}/approve",
                  tokens["admin"],
                  {"supplier_id": supplier_id, "notes": "Aprovado QA"})
        assert ra.status_code == 200

    def test_cancel_quotation(self, client, tokens, quot_product_id):
        rc = post(client, "/api/suppliers/quotations/", tokens["admin"],
                  {"product_id": quot_product_id, "quantity": 5})
        quot_id = rc.get_json()["id"]
        r = post(client, f"/api/suppliers/quotations/{quot_id}/cancel",
                 tokens["admin"], {"reason": "Cancelado nos testes"})
        assert r.status_code == 200
