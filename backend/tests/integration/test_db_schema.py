"""
Integration tests — Database Schema Validation
Verifies that every expected table exists, has the correct columns,
and that all defined indexes exist.
"""
import pytest


# ─── Expected schema ─────────────────────────────────────────────────────────

EXPECTED_TABLES = {
    "users": [
        "id", "name", "email", "password_hash", "role",
        "active", "last_login", "created_at", "updated_at",
    ],
    "categories": [
        "id", "name", "description", "active", "created_at",
    ],
    "products": [
        "id", "name", "description", "sku", "barcode",
        "category_id", "cost_price", "sale_price", "stock",
        "reserved_stock", "min_stock", "unit", "active",
        "created_at", "updated_at",
    ],
    "projects": [
        "id", "name", "description", "cost_center", "manager_id",
        "status", "start_date", "end_date", "created_at", "updated_at",
    ],
    "project_needs": [
        "id", "project_id", "product_id", "quantity_needed",
        "quantity_reserved", "status", "observation",
        "created_at", "updated_at",
    ],
    "suppliers": [
        "id", "name", "cnpj", "email", "phone", "address",
        "contact_name", "rating", "avg_lead_time", "active", "created_at",
    ],
    "product_suppliers": [
        "id", "product_id", "supplier_id", "avg_price",
        "lead_time", "priority", "notes",
    ],
    "movements": [
        "id", "product_id", "type", "quantity", "unit_cost",
        "user_id", "project_id", "supplier_id", "invoice_number",
        "invoice_id", "invoice_item_id", "observation", "created_at",
    ],
    "quotations": [
        "id", "project_need_id", "product_id", "quantity", "status",
        "approved_supplier_id", "notes", "created_at", "updated_at",
    ],
    "quotation_items": [
        "id", "quotation_id", "supplier_id", "unit_price",
        "lead_time", "notes", "status",
    ],
    "invoices": [
        "id", "invoice_number", "supplier_id", "supplier_cnpj",
        "supplier_name", "issue_date", "total_value", "status",
        "xml_content", "cnpj_valid", "source_file_name",
        "pdf_content_base64", "created_at",
    ],
    "invoice_items": [
        "id", "invoice_id", "product_id", "description", "ncm",
        "quantity", "unit", "unit_price", "total_price",
        "matched", "match_confidence", "skipped",
    ],
    "ocr_cache": ["pdf_hash", "result_json", "source", "created_at"],
    "audit_logs": [
        "id", "user_id", "action", "entity_type", "entity_id",
        "details", "ip_address", "created_at",
    ],
    "tools": [
        "id", "name", "brand", "sku", "category", "description",
        "invoice_id", "invoice_number", "unit_value", "total_units",
        "available_units", "min_units", "condition", "photo_base64",
        "active", "created_at", "updated_at",
    ],
    "tool_checkouts": [
        "id", "operator_id", "project_id", "checkout_date",
        "expected_return_date", "actual_return_date", "status",
        "observation", "checkout_photo", "return_photo",
        "renewed_count", "created_by", "created_at", "updated_at",
    ],
    "tool_checkout_items": [
        "id", "checkout_id", "tool_id", "quantity",
        "returned_quantity", "condition_on_return",
        "observation", "returned_at", "created_at",
    ],
}

EXPECTED_INDEXES = [
    "idx_products_sku",
    "idx_products_category",
    "idx_movements_product",
    "idx_movements_created",
    "idx_movements_type",
    "idx_movements_supplier",
    "idx_movements_invoice",
    "idx_movements_invoice_id",
    "idx_project_needs_project",
    "idx_project_needs_product",
    "idx_project_needs_status",
    "idx_projects_status",
    "idx_product_suppliers_product",
    "idx_product_suppliers_supplier",
    "idx_quotations_product",
    "idx_quotations_status",
    "idx_quotation_items_quotation",
    "idx_quotation_items_supplier",
    "idx_invoices_status",
    "idx_invoices_issue_date",
    "idx_invoices_supplier",
    "idx_invoice_items_invoice",
    "idx_invoice_items_product",
    "idx_audit_logs_user",
    "idx_audit_logs_action",
    "idx_audit_logs_entity",
    "idx_audit_logs_created",
    "idx_tools_active",
    "idx_tools_category",
    "idx_tool_checkouts_operator",
    "idx_tool_checkouts_status",
    "idx_tool_checkouts_date",
    "idx_tool_checkout_items_checkout",
    "idx_tool_checkout_items_tool",
]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_db(app):
    """Get a direct connection to the test in-memory DB."""
    import sqlite3
    db_path = app.config["DATABASE"]
    use_uri = str(db_path).startswith("file:")
    con = sqlite3.connect(db_path, uri=use_uri)
    return con


def _table_columns(con, table):
    cur = con.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _existing_indexes(con):
    cur = con.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    )
    return {row[0] for row in cur.fetchall()}


def _existing_tables(con):
    cur = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    return {row[0] for row in cur.fetchall()}


# ─── Tests ───────────────────────────────────────────────────────────────────

class TestTableExistence:
    @pytest.mark.parametrize("table", list(EXPECTED_TABLES.keys()))
    def test_table_exists(self, app, table):
        with app.app_context():
            con = _get_db(app)
            existing = _existing_tables(con)
            con.close()
        assert table in existing, f"Table '{table}' does not exist in DB"


class TestTableColumns:
    @pytest.mark.parametrize("table,columns", EXPECTED_TABLES.items())
    def test_columns_exist(self, app, table, columns):
        with app.app_context():
            con = _get_db(app)
            actual = _table_columns(con, table)
            con.close()
        missing = set(columns) - actual
        assert not missing, \
            f"Table '{table}' is missing columns: {missing}"


class TestIndexExistence:
    @pytest.mark.parametrize("idx", EXPECTED_INDEXES)
    def test_index_exists(self, app, idx):
        with app.app_context():
            con = _get_db(app)
            existing = _existing_indexes(con)
            con.close()
        assert idx in existing, f"Index '{idx}' does not exist"


class TestSchemaConstraints:
    def test_users_email_unique(self, app):
        with app.app_context():
            con = _get_db(app)
            try:
                con.execute("PRAGMA foreign_keys=ON")
                con.execute(
                    "INSERT INTO users (id,name,email,password_hash,role) VALUES (?,?,?,?,?)",
                    ("dup-id-1", "A", "unique_constraint_test@x.com", "h", "operator")
                )
                con.commit()
                con.execute(
                    "INSERT INTO users (id,name,email,password_hash,role) VALUES (?,?,?,?,?)",
                    ("dup-id-2", "B", "unique_constraint_test@x.com", "h", "operator")
                )
                con.commit()
                assert False, "Duplicate email should have raised IntegrityError"
            except Exception as e:
                assert "UNIQUE" in str(e).upper() or "unique" in str(e).lower()
            finally:
                con.rollback()
                con.close()

    def test_products_sku_unique(self, app):
        with app.app_context():
            con = _get_db(app)
            try:
                con.execute(
                    "INSERT INTO products (id,name,sku) VALUES (?,?,?)",
                    ("p-dup-1", "P1", "UNIQUE-SKU-TEST")
                )
                con.commit()
                con.execute(
                    "INSERT INTO products (id,name,sku) VALUES (?,?,?)",
                    ("p-dup-2", "P2", "UNIQUE-SKU-TEST")
                )
                con.commit()
                assert False, "Duplicate SKU should have raised IntegrityError"
            except Exception as e:
                assert "UNIQUE" in str(e).upper() or "unique" in str(e).lower()
            finally:
                con.rollback()
                con.close()

    def test_tool_checkout_items_status_check(self, app):
        """tool_checkouts.status CHECK constraint."""
        with app.app_context():
            con = _get_db(app)
            try:
                con.execute("PRAGMA foreign_keys=OFF")
                con.execute(
                    """INSERT INTO tool_checkouts
                       (id,operator_id,status)
                       VALUES (?,?,?)""",
                    ("tc-bad", "fake-user", "INVALID_STATUS")
                )
                con.commit()
                assert False, "Invalid status should have raised CHECK constraint"
            except Exception as e:
                assert "CHECK" in str(e).upper() or "constraint" in str(e).lower()
            finally:
                con.rollback()
                con.close()

    def test_admin_user_seeded(self, app):
        with app.app_context():
            con = _get_db(app)
            cur = con.execute(
                "SELECT email, role FROM users WHERE email=?",
                ("admin@stock.com",)
            )
            row = cur.fetchone()
            con.close()
        assert row is not None, "Admin user not seeded"
        assert row[1] == "admin"
