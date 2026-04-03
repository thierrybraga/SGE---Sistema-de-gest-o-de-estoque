import sqlite3
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from flask import g, current_app
from werkzeug.security import generate_password_hash

DATABASE_PATH = None


def get_db():
    if "db" not in g:
        db_path = current_app.config["DATABASE"]
        use_uri = str(db_path).startswith("file:")
        g.db = sqlite3.connect(
            db_path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            timeout=30,
            uri=use_uri,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
        g.db.execute("PRAGMA busy_timeout = 30000")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv


def execute_db(query, args=(), commit=True):
    db = get_db()
    cur = db.execute(query, args)
    if commit:
        db.commit()
    return cur


@contextmanager
def db_transaction():
    db = get_db()
    try:
        db.execute("BEGIN")
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


def seed_demo_data(con):
    cur = con.cursor()
    product_count = cur.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    supplier_count = cur.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0]
    project_count = cur.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    if product_count or supplier_count or project_count:
        return False

    admin_row = cur.execute("SELECT id FROM users WHERE email=?", ("admin@stock.com",)).fetchone()
    if not admin_row:
        return False
    admin_id = admin_row[0]

    cat_ids = {}
    for name, desc in [
        ("Materiais", "Insumos básicos de obra"),
        ("Ferramentas", "Ferramentas e equipamentos"),
        ("EPI", "Equipamentos de proteção individual"),
    ]:
        cid = str(uuid.uuid4())
        cur.execute("INSERT INTO categories (id, name, description) VALUES (?,?,?)", (cid, name, desc))
        cat_ids[name] = cid

    products = [
        ("Cimento CP II 50kg", "Saco de cimento para obra", "CEM-50", "789000000001", cat_ids["Materiais"], 28.5, 39.0, 320, 20, "un"),
        ("Areia Média (m³)", "Areia para construção", "ARE-01", "789000000002", cat_ids["Materiais"], 90.0, 140.0, 18, 5, "m3"),
        ("Parafuso 8mm", "Parafuso aço 8mm", "PAR-08", "789000000003", cat_ids["Ferramentas"], 0.25, 0.6, 1500, 300, "un"),
        ("Luva de Segurança", "Luva EPI para obra", "EPI-LUV", "789000000004", cat_ids["EPI"], 4.0, 8.5, 120, 40, "par"),
        ("Serra Mármore 1200W", "Serra elétrica para cortes", "FER-001", "789000000005", cat_ids["Ferramentas"], 280.0, 450.0, 12, 3, "un"),
    ]
    product_ids = {}
    for name, desc, sku, barcode, cat_id, cost, sale, stock, min_stock, unit in products:
        pid = str(uuid.uuid4())
        product_ids[name] = pid
        cur.execute(
            """INSERT INTO products
               (id, name, description, sku, barcode, category_id, cost_price, sale_price, stock, min_stock, unit)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, name, desc, sku, barcode, cat_id, cost, sale, stock, min_stock, unit),
        )

    suppliers = [
        ("Construforte Ltda", "12.345.678/0001-90", "contato@construforte.com", "(11) 3222-1000", "São Paulo - SP", "Marina Costa", 5.0, 6),
        ("Casa do EPI", "98.765.432/0001-55", "vendas@casadoepi.com", "(11) 3888-2000", "Guarulhos - SP", "Paulo Lima", 4.6, 4),
        ("Metal Supply", "45.111.222/0001-10", "comercial@metalsupply.com", "(11) 3555-3000", "Campinas - SP", "Rafaela Sousa", 4.8, 5),
    ]
    supplier_ids = {}
    for name, cnpj, email, phone, address, contact, rating, lead in suppliers:
        sid = str(uuid.uuid4())
        supplier_ids[name] = sid
        cur.execute(
            """INSERT INTO suppliers
               (id, name, cnpj, email, phone, address, contact_name, rating, avg_lead_time)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (sid, name, cnpj, email, phone, address, contact, rating, lead),
        )

    links = [
        ("Cimento CP II 50kg", "Construforte Ltda", 29.0, 6, 1, "Fornecedor principal"),
        ("Cimento CP II 50kg", "Metal Supply", 30.5, 5, 2, "Alternativo"),
        ("Areia Média (m³)", "Construforte Ltda", 88.0, 4, 1, "Entrega rápida"),
        ("Parafuso 8mm", "Metal Supply", 0.22, 5, 1, ""),
        ("Luva de Segurança", "Casa do EPI", 4.2, 3, 1, "EPI padrão"),
        ("Serra Mármore 1200W", "Metal Supply", 275.0, 7, 1, ""),
    ]
    for prod, sup, price, lead, priority, notes in links:
        cur.execute(
            """INSERT INTO product_suppliers
               (id, product_id, supplier_id, avg_price, lead_time, priority, notes)
               VALUES (?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), product_ids[prod], supplier_ids[sup], price, lead, priority, notes),
        )

    projects = [
        ("Obra Alfa", "Construção do galpão industrial", "CC-1001", "active"),
        ("Reforma Beta", "Reforma de escritórios administrativos", "CC-1002", "active"),
    ]
    project_ids = {}
    for name, desc, cc, status in projects:
        pid = str(uuid.uuid4())
        project_ids[name] = pid
        cur.execute(
            """INSERT INTO projects
               (id, name, description, cost_center, manager_id, status, start_date)
               VALUES (?,?,?,?,?,?,date('now','-15 days'))""",
            (pid, name, desc, cc, admin_id, status),
        )

    needs = [
        ("Obra Alfa", "Cimento CP II 50kg", 200, "Pendência de compra"),
        ("Obra Alfa", "Areia Média (m³)", 8, "Entrega programada"),
        ("Reforma Beta", "Luva de Segurança", 40, "Uso imediato"),
    ]
    for project, product, qty, obs in needs:
        cur.execute(
            """INSERT INTO project_needs
               (id, project_id, product_id, quantity_needed, observation)
               VALUES (?,?,?,?,?)""",
            (str(uuid.uuid4()), project_ids[project], product_ids[product], qty, obs),
        )

    qid_open = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO quotations (id, product_id, quantity, status, notes) VALUES (?,?,?,?,?)",
        (qid_open, product_ids["Cimento CP II 50kg"], 120, "open", "Cotação inicial do projeto"),
    )
    for sup in ["Construforte Ltda", "Metal Supply"]:
        cur.execute(
            "INSERT INTO quotation_items (id, quotation_id, supplier_id, unit_price, lead_time, status) VALUES (?,?,?,?,?,?)",
            (str(uuid.uuid4()), qid_open, supplier_ids[sup], 0, 5, "pending"),
        )

    qid_received = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO quotations (id, product_id, quantity, status, notes) VALUES (?,?,?,?,?)",
        (qid_received, product_ids["Luva de Segurança"], 60, "received", "Respostas em análise"),
    )
    cur.execute(
        "INSERT INTO quotation_items (id, quotation_id, supplier_id, unit_price, lead_time, status) VALUES (?,?,?,?,?,?)",
        (str(uuid.uuid4()), qid_received, supplier_ids["Casa do EPI"], 4.15, 3, "pending"),
    )
    cur.execute(
        "INSERT INTO quotation_items (id, quotation_id, supplier_id, unit_price, lead_time, status) VALUES (?,?,?,?,?,?)",
        (str(uuid.uuid4()), qid_received, supplier_ids["Construforte Ltda"], 4.4, 4, "pending"),
    )

    now = datetime.utcnow()
    entries = [
        ("Cimento CP II 50kg", "entry", 150, 28.5, "NF-1001", "Entrada lote A", now - timedelta(days=3)),
        ("Luva de Segurança", "entry", 80, 4.0, "NF-1002", "Entrada EPI", now - timedelta(days=2)),
        ("Cimento CP II 50kg", "exit", 40, 0, None, "Saída para Obra Alfa", now - timedelta(days=1)),
        ("Parafuso 8mm", "entry", 500, 0.22, "NF-1003", "Reposição de estoque", now - timedelta(days=5)),
    ]
    for product, mtype, qty, cost, invoice, obs, created in entries:
        cur.execute(
            """INSERT INTO movements
               (id, product_id, type, quantity, unit_cost, user_id, invoice_number, observation, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()),
                product_ids[product],
                mtype,
                qty,
                cost,
                admin_id,
                invoice,
                obs,
                created.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )

    con.commit()
    return True


def init_db(app):
    db_path = app.config["DATABASE"]
    if db_path == ":memory:":
        db_path = "file:memdb1?mode=memory&cache=shared"
        app.config["DATABASE"] = db_path
    if db_path not in ("",):
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

    app.teardown_appcontext(close_db)

    # Create tables using direct connection
    is_mem = str(db_path).startswith("file:") and "mode=memory" in str(db_path)
    con = sqlite3.connect(db_path, uri=str(db_path).startswith("file:"))
    con.execute("PRAGMA foreign_keys = ON")
    cur = con.cursor()

    schema = """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL DEFAULT '',
        role TEXT DEFAULT 'operator',
        active INTEGER DEFAULT 1,
        must_change_password INTEGER DEFAULT 0,
        last_login TEXT DEFAULT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS categories (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS products (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        sku TEXT UNIQUE,
        barcode TEXT UNIQUE,
        category_id TEXT REFERENCES categories(id),
        cost_price REAL DEFAULT 0.0,
        sale_price REAL DEFAULT 0.0,
        stock REAL DEFAULT 0,
        reserved_stock REAL DEFAULT 0,
        min_stock REAL DEFAULT 0,
        unit TEXT DEFAULT 'un',
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        cost_center TEXT,
        manager_id TEXT REFERENCES users(id),
        status TEXT DEFAULT 'active',
        start_date TEXT,
        end_date TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS project_needs (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        product_id TEXT NOT NULL REFERENCES products(id),
        quantity_needed REAL NOT NULL,
        quantity_reserved REAL DEFAULT 0,
        status TEXT DEFAULT 'pending',
        observation TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS suppliers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        cnpj TEXT UNIQUE,
        email TEXT,
        phone TEXT,
        address TEXT,
        contact_name TEXT,
        rating REAL DEFAULT 5.0,
        avg_lead_time INTEGER DEFAULT 7,
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS product_suppliers (
        id TEXT PRIMARY KEY,
        product_id TEXT NOT NULL REFERENCES products(id),
        supplier_id TEXT NOT NULL REFERENCES suppliers(id),
        avg_price REAL DEFAULT 0.0,
        lead_time INTEGER DEFAULT 7,
        priority INTEGER DEFAULT 1,
        notes TEXT,
        UNIQUE(product_id, supplier_id)
    );

    CREATE TABLE IF NOT EXISTS movements (
        id TEXT PRIMARY KEY,
        product_id TEXT NOT NULL REFERENCES products(id),
        type TEXT NOT NULL CHECK(type IN ('entry','exit','adjustment','reservation')),
        quantity REAL NOT NULL,
        unit_cost REAL DEFAULT 0.0,
        user_id TEXT REFERENCES users(id),
        project_id TEXT REFERENCES projects(id),
        supplier_id TEXT REFERENCES suppliers(id),
        invoice_number TEXT,
        invoice_id TEXT REFERENCES invoices(id),
        invoice_item_id TEXT REFERENCES invoice_items(id),
        observation TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS quotations (
        id TEXT PRIMARY KEY,
        project_need_id TEXT REFERENCES project_needs(id),
        product_id TEXT NOT NULL REFERENCES products(id),
        quantity REAL NOT NULL,
        status TEXT DEFAULT 'open',
        approved_supplier_id TEXT REFERENCES suppliers(id),
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS quotation_items (
        id TEXT PRIMARY KEY,
        quotation_id TEXT NOT NULL REFERENCES quotations(id),
        supplier_id TEXT NOT NULL REFERENCES suppliers(id),
        unit_price REAL DEFAULT 0.0,
        lead_time INTEGER DEFAULT 7,
        notes TEXT,
        status TEXT DEFAULT 'pending'
    );

    CREATE TABLE IF NOT EXISTS invoices (
        id TEXT PRIMARY KEY,
        invoice_number TEXT NOT NULL,
        supplier_id TEXT REFERENCES suppliers(id),
        supplier_cnpj TEXT,
        supplier_name TEXT,
        issue_date TEXT,
        total_value REAL DEFAULT 0.0,
        status TEXT DEFAULT 'pending' CHECK(status IN ('pending','processed','reversed')),
        xml_content TEXT,
        cnpj_valid INTEGER DEFAULT 1,
        source_file_name TEXT,
        pdf_content_base64 TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS invoice_items (
        id TEXT PRIMARY KEY,
        invoice_id TEXT NOT NULL REFERENCES invoices(id),
        product_id TEXT REFERENCES products(id),
        description TEXT,
        ncm TEXT,
        quantity REAL DEFAULT 0.0,
        unit TEXT,
        unit_price REAL DEFAULT 0.0,
        total_price REAL DEFAULT 0.0,
        matched INTEGER DEFAULT 0,
        match_confidence REAL DEFAULT 0.0,
        skipped INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS ocr_cache (
        pdf_hash TEXT PRIMARY KEY,
        result_json TEXT NOT NULL,
        source TEXT DEFAULT 'openai',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
        id TEXT PRIMARY KEY,
        user_id TEXT REFERENCES users(id),
        action TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT,
        details TEXT,
        ip_address TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku);
    CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
    CREATE INDEX IF NOT EXISTS idx_movements_product ON movements(product_id);
    CREATE INDEX IF NOT EXISTS idx_movements_created ON movements(created_at);
    CREATE INDEX IF NOT EXISTS idx_movements_type ON movements(type);
    CREATE INDEX IF NOT EXISTS idx_movements_project ON movements(project_id);
    CREATE INDEX IF NOT EXISTS idx_movements_supplier ON movements(supplier_id);
    CREATE INDEX IF NOT EXISTS idx_movements_invoice ON movements(invoice_number);
    CREATE INDEX IF NOT EXISTS idx_movements_invoice_id ON movements(invoice_id);
    CREATE INDEX IF NOT EXISTS idx_movements_invoice_item_id ON movements(invoice_item_id);
    CREATE INDEX IF NOT EXISTS idx_project_needs_project ON project_needs(project_id);
    CREATE INDEX IF NOT EXISTS idx_project_needs_product ON project_needs(product_id);
    CREATE INDEX IF NOT EXISTS idx_project_needs_status ON project_needs(status);
    CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
    CREATE INDEX IF NOT EXISTS idx_projects_manager ON projects(manager_id);
    CREATE INDEX IF NOT EXISTS idx_product_suppliers_product ON product_suppliers(product_id);
    CREATE INDEX IF NOT EXISTS idx_product_suppliers_supplier ON product_suppliers(supplier_id);
    CREATE INDEX IF NOT EXISTS idx_quotations_product ON quotations(product_id);
    CREATE INDEX IF NOT EXISTS idx_quotations_status ON quotations(status);
    CREATE INDEX IF NOT EXISTS idx_quotation_items_quotation ON quotation_items(quotation_id);
    CREATE INDEX IF NOT EXISTS idx_quotation_items_supplier ON quotation_items(supplier_id);
    CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);
    CREATE INDEX IF NOT EXISTS idx_invoices_issue_date ON invoices(issue_date);
    CREATE INDEX IF NOT EXISTS idx_invoices_supplier ON invoices(supplier_id);
    CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id);
    CREATE INDEX IF NOT EXISTS idx_invoice_items_product ON invoice_items(product_id);
    CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id);
    CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);
    CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_type, entity_id);
    CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at);

    -- ── TOOLS MODULE ─────────────────────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS tools (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        brand TEXT,
        sku TEXT,
        category TEXT,
        description TEXT,
        invoice_id TEXT REFERENCES invoices(id),
        invoice_number TEXT,
        unit_value REAL DEFAULT 0.0,
        total_units INTEGER NOT NULL DEFAULT 1,
        available_units INTEGER NOT NULL DEFAULT 1,
        min_units INTEGER DEFAULT 0,
        condition TEXT DEFAULT 'good' CHECK(condition IN ('new','good','regular','poor','maintenance')),
        photo_base64 TEXT,
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS tool_checkouts (
        id TEXT PRIMARY KEY,
        operator_id TEXT NOT NULL REFERENCES users(id),
        project_id TEXT REFERENCES projects(id),
        checkout_date TEXT DEFAULT (datetime('now')),
        expected_return_date TEXT,
        actual_return_date TEXT,
        status TEXT DEFAULT 'active' CHECK(status IN ('active','returned','overdue','renewed','partial')),
        observation TEXT,
        checkout_photo TEXT,
        return_photo TEXT,
        renewed_count INTEGER DEFAULT 0,
        created_by TEXT REFERENCES users(id),
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS tool_checkout_items (
        id TEXT PRIMARY KEY,
        checkout_id TEXT NOT NULL REFERENCES tool_checkouts(id),
        tool_id TEXT NOT NULL REFERENCES tools(id),
        quantity INTEGER NOT NULL DEFAULT 1,
        returned_quantity INTEGER DEFAULT 0,
        condition_on_return TEXT,
        observation TEXT,
        returned_at TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_tools_active ON tools(active);
    CREATE INDEX IF NOT EXISTS idx_tools_category ON tools(category);
    CREATE INDEX IF NOT EXISTS idx_tool_checkouts_operator ON tool_checkouts(operator_id);
    CREATE INDEX IF NOT EXISTS idx_tool_checkouts_status ON tool_checkouts(status);
    CREATE INDEX IF NOT EXISTS idx_tool_checkouts_date ON tool_checkouts(checkout_date);
    CREATE INDEX IF NOT EXISTS idx_tool_checkout_items_checkout ON tool_checkout_items(checkout_id);
    CREATE INDEX IF NOT EXISTS idx_tool_checkout_items_tool ON tool_checkout_items(tool_id);
    """

    for stmt in schema.split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                cur.execute(stmt)
            except Exception as e:
                if "already exists" not in str(e):
                    print(f"Schema warning: {e}")

    con.commit()

    # --- Migrations: incremental schema additions for existing databases ---
    migrations = [
        # New columns added after initial schema
        "ALTER TABLE invoice_items ADD COLUMN match_confidence REAL DEFAULT 0.0",
        "ALTER TABLE invoice_items ADD COLUMN skipped INTEGER DEFAULT 0",
        "ALTER TABLE invoices ADD COLUMN cnpj_valid INTEGER DEFAULT 1",
        "ALTER TABLE invoices ADD COLUMN source_file_name TEXT",
        "ALTER TABLE invoices ADD COLUMN pdf_content_base64 TEXT",
        "ALTER TABLE invoices ADD COLUMN supplier_id TEXT REFERENCES suppliers(id)",
        "ALTER TABLE invoices ADD COLUMN updated_at TEXT DEFAULT (datetime('now'))",
        "ALTER TABLE movements ADD COLUMN supplier_id TEXT",
        "ALTER TABLE movements ADD COLUMN invoice_number TEXT",
        "ALTER TABLE movements ADD COLUMN unit_cost REAL DEFAULT 0.0",
        "ALTER TABLE movements ADD COLUMN invoice_id TEXT",
        "ALTER TABLE movements ADD COLUMN invoice_item_id TEXT",
        "ALTER TABLE categories ADD COLUMN active INTEGER DEFAULT 1",
        "ALTER TABLE categories ADD COLUMN created_at TEXT DEFAULT (datetime('now'))",
        "ALTER TABLE projects ADD COLUMN updated_at TEXT DEFAULT (datetime('now'))",
        "ALTER TABLE project_needs ADD COLUMN updated_at TEXT DEFAULT (datetime('now'))",
        "ALTER TABLE suppliers ADD COLUMN updated_at TEXT DEFAULT (datetime('now'))",
        # Indexes
        "CREATE INDEX IF NOT EXISTS idx_invoices_supplier ON invoices(supplier_id)",
        "CREATE INDEX IF NOT EXISTS idx_movements_invoice ON movements(invoice_number)",
        # Audit + last_login + must_change_password
        "ALTER TABLE users ADD COLUMN last_login TEXT DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0",
        """CREATE TABLE IF NOT EXISTS audit_logs (
            id TEXT PRIMARY KEY,
            user_id TEXT REFERENCES users(id),
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT,
            details TEXT,
            ip_address TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action)",
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_type, entity_id)",
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at)",
        # Tools module tables
        """CREATE TABLE IF NOT EXISTS tools (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, brand TEXT, sku TEXT, category TEXT,
            description TEXT, invoice_id TEXT REFERENCES invoices(id), invoice_number TEXT,
            unit_value REAL DEFAULT 0.0, total_units INTEGER NOT NULL DEFAULT 1,
            available_units INTEGER NOT NULL DEFAULT 1, min_units INTEGER DEFAULT 0,
            condition TEXT DEFAULT 'good', photo_base64 TEXT, active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
        )""",
        """CREATE TABLE IF NOT EXISTS tool_checkouts (
            id TEXT PRIMARY KEY, operator_id TEXT NOT NULL REFERENCES users(id),
            project_id TEXT REFERENCES projects(id),
            checkout_date TEXT DEFAULT (datetime('now')), expected_return_date TEXT,
            actual_return_date TEXT, status TEXT DEFAULT 'active',
            observation TEXT, checkout_photo TEXT, return_photo TEXT,
            renewed_count INTEGER DEFAULT 0, created_by TEXT REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
        )""",
        """CREATE TABLE IF NOT EXISTS tool_checkout_items (
            id TEXT PRIMARY KEY, checkout_id TEXT NOT NULL REFERENCES tool_checkouts(id),
            tool_id TEXT NOT NULL REFERENCES tools(id), quantity INTEGER NOT NULL DEFAULT 1,
            returned_quantity INTEGER DEFAULT 0, condition_on_return TEXT,
            observation TEXT, returned_at TEXT, created_at TEXT DEFAULT (datetime('now'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_tools_active ON tools(active)",
        "CREATE INDEX IF NOT EXISTS idx_tools_category ON tools(category)",
        "CREATE INDEX IF NOT EXISTS idx_tool_checkouts_operator ON tool_checkouts(operator_id)",
        "CREATE INDEX IF NOT EXISTS idx_tool_checkouts_status ON tool_checkouts(status)",
        "CREATE INDEX IF NOT EXISTS idx_tool_checkouts_date ON tool_checkouts(checkout_date)",
        "CREATE INDEX IF NOT EXISTS idx_tool_checkout_items_checkout ON tool_checkout_items(checkout_id)",
        "CREATE INDEX IF NOT EXISTS idx_tool_checkout_items_tool ON tool_checkout_items(tool_id)",
        # ── PURCHASE ORDERS MODULE ──
        """CREATE TABLE IF NOT EXISTS purchase_orders (
            id TEXT PRIMARY KEY,
            po_number TEXT UNIQUE NOT NULL,
            quotation_id TEXT REFERENCES quotations(id),
            supplier_id TEXT NOT NULL REFERENCES suppliers(id),
            status TEXT DEFAULT 'draft' CHECK(status IN ('draft','sent','partial','received','cancelled')),
            total_value REAL DEFAULT 0.0,
            notes TEXT,
            expected_delivery TEXT,
            invoice_id TEXT REFERENCES invoices(id),
            created_by TEXT REFERENCES users(id),
            approved_by TEXT REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )""",
        """CREATE TABLE IF NOT EXISTS purchase_order_items (
            id TEXT PRIMARY KEY,
            po_id TEXT NOT NULL REFERENCES purchase_orders(id),
            product_id TEXT NOT NULL REFERENCES products(id),
            quantity REAL NOT NULL,
            unit_price REAL DEFAULT 0.0,
            received_quantity REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_po_status ON purchase_orders(status)",
        "CREATE INDEX IF NOT EXISTS idx_po_supplier ON purchase_orders(supplier_id)",
        "CREATE INDEX IF NOT EXISTS idx_po_items_po ON purchase_order_items(po_id)",
        # ── MOVEMENT APPROVALS ──
        "ALTER TABLE movements ADD COLUMN approval_status TEXT DEFAULT 'approved'",
        "ALTER TABLE movements ADD COLUMN approved_by TEXT",
        "ALTER TABLE movements ADD COLUMN approval_notes TEXT",
        # ── MULTI-WAREHOUSE ──
        """CREATE TABLE IF NOT EXISTS warehouses (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            code TEXT UNIQUE,
            address TEXT,
            is_default INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        )""",
        "ALTER TABLE products ADD COLUMN warehouse_id TEXT",
        "ALTER TABLE movements ADD COLUMN warehouse_id TEXT",
        # ── PHYSICAL INVENTORY ──
        """CREATE TABLE IF NOT EXISTS inventory_sessions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT DEFAULT 'open' CHECK(status IN ('open','counting','review','closed')),
            warehouse_id TEXT,
            created_by TEXT REFERENCES users(id),
            closed_by TEXT REFERENCES users(id),
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            closed_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS inventory_counts (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES inventory_sessions(id),
            product_id TEXT NOT NULL REFERENCES products(id),
            system_quantity REAL NOT NULL,
            counted_quantity REAL,
            difference REAL,
            adjusted INTEGER DEFAULT 0,
            counted_by TEXT REFERENCES users(id),
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_inv_session_status ON inventory_sessions(status)",
        "CREATE INDEX IF NOT EXISTS idx_inv_counts_session ON inventory_counts(session_id)",
        # ── ATTACHMENTS ──
        """CREATE TABLE IF NOT EXISTS attachments (
            id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_type TEXT,
            file_size INTEGER,
            file_data TEXT,
            description TEXT,
            uploaded_by TEXT REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_attachments_entity ON attachments(entity_type, entity_id)",
        # ── SYSTEM SETTINGS ──
        """CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        )""",
        "INSERT OR IGNORE INTO system_settings (key, value) VALUES ('movement_approval_threshold', '0')",
        "INSERT OR IGNORE INTO system_settings (key, value) VALUES ('email_alerts_enabled', '0')",
        "INSERT OR IGNORE INTO system_settings (key, value) VALUES ('smtp_host', '')",
        "INSERT OR IGNORE INTO system_settings (key, value) VALUES ('smtp_port', '587')",
        "INSERT OR IGNORE INTO system_settings (key, value) VALUES ('smtp_user', '')",
        "INSERT OR IGNORE INTO system_settings (key, value) VALUES ('smtp_password', '')",
        "INSERT OR IGNORE INTO system_settings (key, value) VALUES ('alert_email_to', '')",
        "INSERT OR IGNORE INTO warehouses (id, name, code, is_default) VALUES ('default', 'Almoxarifado Principal', 'ALM-01', 1)",
    ]
    for stmt in migrations:
        stmt = stmt.strip()
        if stmt:
            try:
                cur.execute(stmt)
            except Exception as e:
                if "duplicate column name" not in str(e).lower() and "already exists" not in str(e).lower():
                    print(f"Migration warning: {e}")
    con.commit()

    # Seed admin user
    admin_id = str(uuid.uuid4())
    pwd_hash = generate_password_hash("admin123")
    con.execute(
        "INSERT OR IGNORE INTO users (id, name, email, password_hash, role) VALUES (?,?,?,?,?)",
        (admin_id, "Administrador", "admin@stock.com", pwd_hash, "admin"),
    )
    con.commit()

    # Seed POC users (Vitória Luz) — only if they don't exist yet
    poc_users = [
        ("Admin Principal",      "admin@vitorialuz.com",             "Admin@2026",      "admin",    1),
        ("Admin Secundário",     "admin2@vitorialuz.com",            "Admin@2026",      "admin",    1),
        ("Geraldo Mendes",       "gerente.geral@vitorialuz.com",     "Gerente@2026",    "manager",  1),
        ("Patricia Lima",        "gerente.operacoes@vitorialuz.com", "Gerente@2026",    "manager",  1),
        ("Marcos Souza",         "operador.campo@vitorialuz.com",    "Operador@2026",   "operator", 1),
        ("Fernanda Costa",       "operador.logistica@vitorialuz.com","Operador@2026",   "operator", 1),
        ("Ana Paula Rocha",      "comprador.senior@vitorialuz.com",  "Comprador@2026",  "buyer",    1),
        ("Diego Ferreira",       "comprador.junior@vitorialuz.com",  "Comprador@2026",  "buyer",    1),
    ]
    for name, email, password, role, must_change in poc_users:
        existing = con.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if not existing:
            con.execute(
                "INSERT INTO users (id, name, email, password_hash, role, must_change_password) VALUES (?,?,?,?,?,?)",
                (str(uuid.uuid4()), name, email, generate_password_hash(password), role, must_change),
            )
    con.commit()

    if os.environ.get("DEMO_SEED") == "1":
        seed_demo_data(con)

    if is_mem:
        app.config["_MEMORY_DB_CONN"] = con
    else:
        con.close()
