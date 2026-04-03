"""
Integration / Functional tests — End-to-End Workflows
Tests complete business flows that span multiple modules.
"""
import io
import pytest
from datetime import date, timedelta
from tests.conftest import get, post, put, _login


# ─── Workflow 1: Product purchase cycle ──────────────────────────────────────
# Product created → Supplier linked → Quotation raised →
# Quotation approved → Entry movement recorded

class TestPurchaseCycleWorkflow:
    @pytest.fixture(scope="class")
    def setup(self, client, tokens):
        # Create product
        p = post(client, "/api/products/", tokens["admin"],
                 {"name": "Cimento Workflow", "sku": "WF-CIM-001",
                  "cost_price": 28.0, "sale_price": 39.0,
                  "stock": 0, "min_stock": 50, "unit": "saco"}).get_json()

        # Create supplier
        s = post(client, "/api/suppliers/", tokens["admin"],
                 {"name": "Cimenteira Workflow",
                  "cnpj": "33.444.555/0001-81"}).get_json()

        # Link product → supplier
        lnk = post(client, "/api/suppliers/product-link", tokens["admin"],
                   {"supplier_id": s["id"], "product_id": p["id"],
                    "avg_price": 28.5, "lead_time": 4, "priority": 1}).get_json()

        # Create quotation
        q = post(client, "/api/suppliers/quotations/", tokens["admin"],
                 {"product_id": p["id"], "quantity": 100,
                  "supplier_ids": [s["id"]]}).get_json()

        return {"product": p, "supplier": s, "link": lnk, "quotation": q}

    def test_product_created(self, setup):
        assert setup["product"].get("id")

    def test_supplier_created(self, setup):
        assert setup["supplier"].get("id")

    def test_link_created(self, setup):
        assert setup["link"].get("id")

    def test_quotation_created(self, setup):
        q = setup["quotation"]
        assert q.get("id")
        assert q.get("status") == "open"

    def test_buyer_updates_price(self, client, tokens, setup):
        q = setup["quotation"]
        items = q.get("items") or \
                get(client, "/api/suppliers/quotations/", tokens["admin"]
                    ).get_json()
        # Find this quotation's items
        q_full = next((x for x in
                       get(client, "/api/suppliers/quotations/",
                           tokens["admin"]).get_json()
                       if x["id"] == q["id"]), None)
        assert q_full
        if q_full.get("items"):
            item_id = q_full["items"][0]["id"]
            r = put(client, f"/api/suppliers/quotation-items/{item_id}",
                    tokens["buyer"], {"unit_price": 28.5, "lead_time": 4})
            assert r.status_code == 200

    def test_approve_quotation(self, client, tokens, setup):
        q_id = setup["quotation"]["id"]
        s_id = setup["supplier"]["id"]
        r = post(client, f"/api/suppliers/quotations/{q_id}/approve",
                 tokens["admin"],
                 {"supplier_id": s_id, "notes": "Aprovado workflow"})
        assert r.status_code == 200
        q = get(client, "/api/suppliers/quotations/",
                tokens["admin"]).get_json()
        approved = next((x for x in q if x["id"] == q_id), None)
        if approved:
            assert approved["status"] == "approved"

    def test_entry_movement_after_approval(self, client, tokens, setup):
        r = post(client, "/api/movements/entry", tokens["admin"],
                 {"product_id": setup["product"]["id"],
                  "quantity": 100, "unit_cost": 28.5,
                  "invoice_number": "NF-WF-001",
                  "observation": "Recebimento workflow"})
        assert r.status_code == 201
        # Verify stock updated
        p = get(client, f"/api/products/{setup['product']['id']}",
                tokens["admin"]).get_json()
        assert p["stock"] == 100


# ─── Workflow 2: Tool checkout and return ────────────────────────────────────

class TestToolCheckoutWorkflow:
    @pytest.fixture(scope="class")
    def setup(self, client, tokens):
        # Create tool with 3 units
        tool = post(client, "/api/tools/", tokens["admin"],
                    {"name": "Nível Workflow", "brand": "Bosch",
                     "category": "Medição", "total_units": 3,
                     "unit_value": 80.0, "min_units": 1}).get_json()

        op_id = get(client, "/api/auth/me", tokens["operator"]).get_json()["id"]
        due = (date.today() + timedelta(days=5)).isoformat()

        # Checkout 2 of 3 units
        co = post(client, "/api/tools/checkouts/", tokens["admin"],
                  {"operator_id": op_id,
                   "expected_return_date": due,
                   "items": [{"tool_id": tool["id"], "quantity": 2}]
                   }).get_json()
        return {"tool": tool, "checkout": co, "op_id": op_id}

    def test_available_units_decremented(self, client, tokens, setup):
        t = get(client, f"/api/tools/{setup['tool']['id']}",
                tokens["admin"]).get_json()
        assert t["available_units"] == 1

    def test_units_in_use_correct(self, client, tokens, setup):
        t = get(client, f"/api/tools/{setup['tool']['id']}",
                tokens["admin"]).get_json()
        assert t.get("units_in_use") == 2

    def test_summary_reflects_checkout(self, client, tokens):
        r = get(client, "/api/tools/report/summary", tokens["admin"])
        s = r.get_json()
        assert s["active_checkouts"] >= 1

    def test_renew_extends_due_date(self, client, tokens, setup):
        co_id = setup["checkout"]["id"]
        new_due = (date.today() + timedelta(days=14)).isoformat()
        r = post(client, f"/api/tools/checkouts/{co_id}/renew",
                 tokens["admin"],
                 {"new_return_date": new_due, "reason": "Obra estendida"})
        assert r.status_code == 200
        co = get(client, f"/api/tools/checkouts/{co_id}",
                 tokens["admin"]).get_json()
        assert co.get("expected_return_date") == new_due
        assert co.get("renewed_count", 0) >= 1

    def test_full_return_restores_units(self, client, tokens, setup):
        co_id = setup["checkout"]["id"]
        tool_id = setup["tool"]["id"]
        items = get(client, f"/api/tools/checkouts/{co_id}",
                    tokens["admin"]).get_json()["items"]
        r = post(client, f"/api/tools/checkouts/{co_id}/return",
                 tokens["admin"],
                 {"items": [{"tool_id": items[0]["tool_id"],
                              "returned_quantity": 2,
                              "condition_on_return": "good"}]})
        assert r.status_code == 200
        t = get(client, f"/api/tools/{tool_id}", tokens["admin"]).get_json()
        assert t["available_units"] == 3

    def test_checkout_status_returned(self, client, tokens, setup):
        co = get(client, f"/api/tools/checkouts/{setup['checkout']['id']}",
                 tokens["admin"]).get_json()
        assert co["status"] == "returned"


# ─── Workflow 3: Invoice → supplier link → process ───────────────────────────

class TestInvoiceWorkflow:
    @pytest.fixture(scope="class")
    def setup(self, client, tokens):
        # Create supplier
        sup = post(client, "/api/suppliers/", tokens["admin"],
                   {"name": "Emissor NF Workflow",
                    "cnpj": "44.555.666/0001-81"}).get_json()

        # Import a minimal NF-e XML
        nfe_xml = """<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe">
 <NFe><infNFe>
  <ide><nNF>7777</nNF><dhEmi>2024-03-01T10:00:00-03:00</dhEmi></ide>
  <emit><CNPJ>44555666000181</CNPJ><xNome>Emissor NF Workflow</xNome></emit>
  <dest><CNPJ>11222333000181</CNPJ></dest>
  <det nItem="1">
   <prod>
    <xProd>Produto Workflow NF</xProd><NCM>84715000</NCM>
    <qCom>20</qCom><uCom>UN</uCom><vUnCom>15.00</vUnCom><vProd>300.00</vProd>
   </prod>
  </det>
  <total><ICMSTot><vNF>300.00</vNF></ICMSTot></total>
 </infNFe></NFe>
</nfeProc>"""
        r = client.post(
            "/api/invoices/import-xml",
            data={"file": (io.BytesIO(nfe_xml.encode()), "wf_nfe.xml")},
            content_type="multipart/form-data",
            headers={"Authorization": f"Bearer {tokens['admin']}"},
        )
        inv = r.get_json()
        return {"supplier": sup, "invoice": inv}

    def test_invoice_imported(self, setup):
        inv = setup["invoice"]
        assert inv.get("id")
        assert inv.get("invoice_number") == "7777"

    def test_link_supplier_to_invoice(self, client, tokens, setup):
        inv_id = setup["invoice"]["id"]
        sup_id = setup["supplier"]["id"]
        r = post(client, f"/api/invoices/{inv_id}/link-supplier",
                 tokens["admin"], {"supplier_id": sup_id})
        assert r.status_code == 200

    def test_invoice_supplier_persisted(self, client, tokens, setup):
        inv_id = setup["invoice"]["id"]
        r = get(client, f"/api/invoices/{inv_id}", tokens["admin"])
        inv = r.get_json()
        assert inv.get("supplier_id") == setup["supplier"]["id"] or \
               inv.get("supplier_name")  # either FK or name present


# ─── Workflow 4: Role hierarchy boundary ─────────────────────────────────────

class TestRoleHierarchy:
    """
    Verifies the four-role hierarchy:
    admin > manager > operator > buyer
    """

    def test_admin_can_do_all(self, client, tokens):
        r = get(client, "/api/auth/users", tokens["admin"])
        assert r.status_code == 200

    def test_manager_can_register_users(self, client, tokens):
        r = post(client, "/api/auth/register", tokens["manager"],
                 {"name": "MgrCreated", "email": "mgr_created@test.com",
                  "password": "Pass12345", "role": "operator"})
        assert r.status_code in (200, 201, 409)

    def test_operator_cannot_manage_users(self, client, tokens):
        r = get(client, "/api/auth/users", tokens["operator"])
        assert r.status_code == 403

    def test_buyer_can_list_invoices(self, client, tokens):
        r = get(client, "/api/invoices/", tokens["buyer"])
        assert r.status_code == 200

    def test_buyer_cannot_record_movement(self, client, tokens):
        products = get(client, "/api/products/", tokens["admin"]).get_json()
        if products:
            r = post(client, "/api/movements/entry", tokens["buyer"],
                     {"product_id": products[0]["id"], "quantity": 1})
            assert r.status_code == 403

    def test_unauthenticated_rejected_everywhere(self, client):
        for path in [
            "/api/products/", "/api/movements/", "/api/projects/",
            "/api/suppliers/", "/api/invoices/", "/api/tools/",
            "/api/dashboard/summary", "/api/audit/",
        ]:
            r = client.get(path)
            assert r.status_code == 401, f"Expected 401 on {path}, got {r.status_code}"
