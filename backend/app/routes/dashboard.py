from flask import Blueprint, jsonify, request
from app.core.jwt_utils import require_role
from app.core.database import query_db, rows_to_dicts

dashboard_bp = Blueprint("dashboard", __name__)

@dashboard_bp.route("/summary", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def summary():
    total_products = query_db("SELECT COUNT(*) as c FROM products WHERE active=1", one=True)["c"]
    stock_value = query_db("SELECT COALESCE(SUM(stock * cost_price), 0) as v FROM products WHERE active=1", one=True)["v"]
    low_stock = query_db("SELECT COUNT(*) as c FROM products WHERE stock <= min_stock AND active=1 AND min_stock > 0", one=True)["c"]
    active_projects = query_db("SELECT COUNT(*) as c FROM projects WHERE status='active'", one=True)["c"]
    open_quotations = query_db("SELECT COUNT(*) as c FROM quotations WHERE status IN ('open','received')", one=True)["c"]
    total_users = query_db("SELECT COUNT(*) as c FROM users WHERE active=1", one=True)["c"]
    recent_entries = query_db(
        "SELECT COUNT(*) as c FROM movements WHERE type='entry' AND approval_status != 'revoked' AND date(created_at) >= date('now', '-30 days')",
        one=True)["c"]
    recent_exits = query_db(
        "SELECT COUNT(*) as c FROM movements WHERE type='exit' AND approval_status != 'revoked' AND date(created_at) >= date('now', '-30 days')",
        one=True)["c"]
    return jsonify({
        "total_products": total_products, "total_stock_value": round(stock_value, 2),
        "low_stock_count": low_stock, "active_projects": active_projects,
        "open_quotations": open_quotations, "total_users": total_users,
        "recent_entries": recent_entries, "recent_exits": recent_exits,
    })


@dashboard_bp.route("/movements-chart", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def movements_chart():
    """Returns daily entry/exit counts for the last 30 days."""
    days = 30
    rows = query_db("""
        SELECT date(created_at) as day,
               SUM(CASE WHEN type='entry' THEN 1 ELSE 0 END) as entries,
               SUM(CASE WHEN type='exit'  THEN 1 ELSE 0 END) as exits
        FROM movements
        WHERE approval_status != 'revoked'
          AND date(created_at) >= date('now', '-30 days')
        GROUP BY day
        ORDER BY day ASC
    """)
    return jsonify(rows_to_dicts(rows))


@dashboard_bp.route("/stock-by-category", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def stock_by_category():
    """Returns total stock value grouped by category."""
    rows = query_db("""
        SELECT COALESCE(c.name, 'Sem categoria') as category,
               COUNT(p.id) as product_count,
               COALESCE(SUM(p.stock * p.cost_price), 0) as total_value,
               COALESCE(SUM(p.stock), 0) as total_units
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.active = 1
        GROUP BY c.name
        ORDER BY total_value DESC
    """)
    return jsonify(rows_to_dicts(rows))


@dashboard_bp.route("/top-products", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def top_products():
    """Returns top 8 products by total stock value."""
    rows = query_db("""
        SELECT p.name, p.sku, p.stock, p.cost_price,
               COALESCE(c.name, 'Sem categoria') as category,
               (p.stock * p.cost_price) as total_value
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.active = 1 AND p.stock > 0
        ORDER BY total_value DESC
        LIMIT 8
    """)
    return jsonify(rows_to_dicts(rows))

@dashboard_bp.route("/low-stock", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def low_stock():
    rows = query_db("SELECT * FROM products WHERE stock <= min_stock AND active=1 ORDER BY stock ASC LIMIT 10")
    return jsonify(rows_to_dicts(rows))

@dashboard_bp.route("/recent-movements", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def recent_movements():
    rows = query_db("""SELECT m.*, p.name as product_name, u.name as user_name
                       FROM movements m
                       LEFT JOIN products p ON m.product_id = p.id
                       LEFT JOIN users u ON m.user_id = u.id
                       ORDER BY m.created_at DESC LIMIT 10""")
    return jsonify(rows_to_dicts(rows))

@dashboard_bp.route("/pending-needs", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def pending_needs():
    rows = query_db("""SELECT pn.*, p.name as product_name, proj.name as project_name
                       FROM project_needs pn
                       LEFT JOIN products p ON pn.product_id = p.id
                       LEFT JOIN projects proj ON pn.project_id = proj.id
                       WHERE pn.status IN ('pending', 'partial')
                       ORDER BY pn.created_at DESC LIMIT 10""")
    result = []
    for row in rows:
        d = dict(row)
        d["quantity_missing"] = max(0, d["quantity_needed"] - d["quantity_reserved"])
        result.append(d)
    return jsonify(result)


@dashboard_bp.route("/search", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def global_search():
    """Unified search across products, suppliers, invoices, projects."""
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify({"results": []})

    term = f"%{q}%"
    results = []

    # Products
    products = query_db("""
        SELECT id, name, sku, stock, cost_price
        FROM products WHERE active=1 AND (name LIKE ? OR sku LIKE ? OR barcode LIKE ?)
        LIMIT 5
    """, (term, term, term))
    for p in products:
        d = dict(p)
        results.append({
            "type": "product", "icon": "fa-boxes", "color": "#00e5ff",
            "title": d["name"], "subtitle": f"SKU: {d['sku'] or '—'} | Estoque: {d['stock']}",
            "link": "/products", "id": d["id"]
        })

    # Suppliers
    suppliers = query_db("""
        SELECT id, name, cnpj, email
        FROM suppliers WHERE active=1 AND (name LIKE ? OR cnpj LIKE ? OR email LIKE ?)
        LIMIT 5
    """, (term, term, term))
    for s in suppliers:
        d = dict(s)
        results.append({
            "type": "supplier", "icon": "fa-truck", "color": "#7c3aed",
            "title": d["name"], "subtitle": f"CNPJ: {d['cnpj'] or '—'}",
            "link": "/suppliers", "id": d["id"]
        })

    # Invoices
    invoices = query_db("""
        SELECT id, invoice_number, supplier_name, total_value, status
        FROM invoices WHERE invoice_number LIKE ? OR supplier_name LIKE ? OR supplier_cnpj LIKE ?
        LIMIT 5
    """, (term, term, term))
    for inv in invoices:
        d = dict(inv)
        results.append({
            "type": "invoice", "icon": "fa-file-invoice", "color": "#f59e0b",
            "title": f"NF {d['invoice_number']}", "subtitle": f"{d['supplier_name'] or '—'} | {d['status']}",
            "link": "/invoices", "id": d["id"]
        })

    # Projects
    projects = query_db("""
        SELECT id, name, cost_center, status
        FROM projects WHERE name LIKE ? OR cost_center LIKE ?
        LIMIT 5
    """, (term, term))
    for proj in projects:
        d = dict(proj)
        results.append({
            "type": "project", "icon": "fa-project-diagram", "color": "#10b981",
            "title": d["name"], "subtitle": f"CC: {d['cost_center'] or '—'} | {d['status']}",
            "link": "/projects", "id": d["id"]
        })

    return jsonify({"results": results, "total": len(results)})


@dashboard_bp.route("/charts/movements-over-time", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def movements_over_time():
    """Daily entries and exits for the last N days (default 30)."""
    days = min(int(request.args.get("days", 30)), 365)
    rows = query_db("""
        SELECT date(created_at) as day,
               SUM(CASE WHEN type='entry' THEN quantity ELSE 0 END) as entries,
               SUM(CASE WHEN type='exit' THEN quantity ELSE 0 END) as exits
        FROM movements
        WHERE datetime(created_at) >= datetime('now', ?)
        GROUP BY date(created_at)
        ORDER BY day
    """, (f"-{days} days",))
    return jsonify(rows_to_dicts(rows))


@dashboard_bp.route("/charts/stock-value-by-category", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def stock_value_by_category():
    """Stock value grouped by category."""
    rows = query_db("""
        SELECT COALESCE(c.name, 'Sem Categoria') as category,
               SUM(p.stock * p.cost_price) as value
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.active = 1
        GROUP BY COALESCE(c.name, 'Sem Categoria')
        HAVING value > 0
        ORDER BY value DESC
    """)
    return jsonify(rows_to_dicts(rows))


@dashboard_bp.route("/charts/top-products-value", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def top_products_value():
    """Top 10 products by stock value."""
    rows = query_db("""
        SELECT name, stock, cost_price, (stock * cost_price) as total_value
        FROM products
        WHERE active = 1 AND stock > 0
        ORDER BY total_value DESC
        LIMIT 10
    """)
    return jsonify(rows_to_dicts(rows))


@dashboard_bp.route("/charts/movements-by-type", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def movements_by_type():
    """Movement counts by type for the last N days (default 30)."""
    days = min(int(request.args.get("days", 30)), 365)
    rows = query_db("""
        SELECT type, COUNT(*) as count, SUM(quantity) as total_quantity
        FROM movements
        WHERE datetime(created_at) >= datetime('now', ?)
        GROUP BY type
    """, (f"-{days} days",))
    return jsonify(rows_to_dicts(rows))


@dashboard_bp.route("/notifications", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def notifications():
    """Aggregated notifications: low stock, overdue tools, pending quotations."""
    notifs = []

    # Low stock products
    low_stock = query_db("""
        SELECT id, name, sku, stock, min_stock
        FROM products WHERE stock <= min_stock AND active=1
        ORDER BY (stock * 1.0 / CASE WHEN min_stock > 0 THEN min_stock ELSE 1 END) ASC
        LIMIT 20
    """)
    for p in low_stock:
        d = dict(p)
        severity = "critical" if d["stock"] == 0 else "warning"
        notifs.append({
            "type": "low_stock",
            "severity": severity,
            "title": "Estoque zerado" if d["stock"] == 0 else "Estoque baixo",
            "message": f"{d['name']} — {d['stock']}/{d['min_stock']} un",
            "link": "/products",
            "entity_id": d["id"]
        })

    # Overdue tool checkouts
    overdue = query_db("""
        SELECT tc.id, u.name as operator_name, tc.expected_return_date,
               GROUP_CONCAT(t.name, ', ') as tool_names
        FROM tool_checkouts tc
        LEFT JOIN users u ON tc.operator_id = u.id
        LEFT JOIN tool_checkout_items tci ON tci.checkout_id = tc.id
        LEFT JOIN tools t ON tci.tool_id = t.id
        WHERE tc.status IN ('active', 'overdue')
          AND date(tc.expected_return_date) < date('now')
        GROUP BY tc.id
        ORDER BY tc.expected_return_date ASC
        LIMIT 10
    """)
    for row in overdue:
        d = dict(row)
        notifs.append({
            "type": "overdue_tool",
            "severity": "warning",
            "title": "Ferramenta atrasada",
            "message": f"{d['tool_names'] or 'Ferramentas'} — {d['operator_name'] or 'Operador'} (prev. {d['expected_return_date']})",
            "link": "/tools",
            "entity_id": d["id"]
        })

    # Pending quotations
    pending_quotes = query_db("""
        SELECT q.id, p.name as product_name, q.status,
               COUNT(qi.id) as bids_count
        FROM quotations q
        LEFT JOIN products p ON q.product_id = p.id
        LEFT JOIN quotation_items qi ON qi.quotation_id = q.id
        WHERE q.status IN ('open', 'received')
        GROUP BY q.id
        ORDER BY q.created_at DESC
        LIMIT 10
    """)
    for row in pending_quotes:
        d = dict(row)
        status_msg = "aguardando propostas" if d["status"] == "open" else f"{d['bids_count']} proposta(s) recebida(s)"
        notifs.append({
            "type": "pending_quotation",
            "severity": "info",
            "title": "Cotação pendente",
            "message": f"{d['product_name'] or 'Produto'} — {status_msg}",
            "link": "/suppliers",
            "entity_id": d["id"]
        })

    return jsonify({
        "notifications": notifs,
        "total": len(notifs),
        "counts": {
            "low_stock": len([n for n in notifs if n["type"] == "low_stock"]),
            "overdue_tools": len([n for n in notifs if n["type"] == "overdue_tool"]),
            "pending_quotations": len([n for n in notifs if n["type"] == "pending_quotation"]),
        }
    })
