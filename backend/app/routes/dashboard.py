from flask import Blueprint, jsonify
from app.core.jwt_utils import require_role
from app.core.database import query_db, rows_to_dicts

dashboard_bp = Blueprint("dashboard", __name__)

@dashboard_bp.route("/summary", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def summary():
    total_products = query_db("SELECT COUNT(*) as c FROM products WHERE active=1", one=True)["c"]
    stock_value = query_db("SELECT COALESCE(SUM(stock * cost_price), 0) as v FROM products WHERE active=1", one=True)["v"]
    low_stock = query_db("SELECT COUNT(*) as c FROM products WHERE stock <= min_stock AND active=1", one=True)["c"]
    active_projects = query_db("SELECT COUNT(*) as c FROM projects WHERE status='active'", one=True)["c"]
    open_quotations = query_db("SELECT COUNT(*) as c FROM quotations WHERE status IN ('open','received')", one=True)["c"]
    total_users = query_db("SELECT COUNT(*) as c FROM users WHERE active=1", one=True)["c"]
    recent_entries = query_db("SELECT COUNT(*) as c FROM movements WHERE type='entry' AND datetime(created_at) >= datetime('now', '-7 days')", one=True)["c"]
    recent_exits = query_db("SELECT COUNT(*) as c FROM movements WHERE type='exit' AND datetime(created_at) >= datetime('now', '-7 days')", one=True)["c"]
    return jsonify({
        "total_products": total_products, "total_stock_value": round(stock_value, 2),
        "low_stock_count": low_stock, "active_projects": active_projects,
        "open_quotations": open_quotations, "total_users": total_users,
        "recent_entries": recent_entries, "recent_exits": recent_exits,
    })

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
