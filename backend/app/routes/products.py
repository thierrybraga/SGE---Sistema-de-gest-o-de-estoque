from flask import Blueprint, request, jsonify
from app.core.jwt_utils import require_role
from app.core.database import query_db, execute_db, row_to_dict, rows_to_dicts
import uuid

products_bp = Blueprint("products", __name__)

def product_row(row):
    d = dict(row)
    d["is_low_stock"] = d.get("stock", 0) <= d.get("min_stock", 0)
    d["available_stock"] = d.get("stock", 0) - d.get("reserved_stock", 0)
    return d

@products_bp.route("/", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def list_products():
    search = request.args.get("search", "")
    category_id = request.args.get("category_id", "")
    active_only = request.args.get("active_only", "true").lower() == "true"
    q = """
        SELECT p.*, c.name as category_name FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE 1=1
    """
    args = []
    if active_only:
        q += " AND p.active=1"
    if search:
        q += " AND (p.name LIKE ? OR p.sku LIKE ? OR p.barcode LIKE ?)"
        args += [f"%{search}%", f"%{search}%", f"%{search}%"]
    if category_id:
        q += " AND p.category_id=?"
        args.append(category_id)
    q += " ORDER BY p.name"
    rows = query_db(q, args)
    result = []
    for row in rows:
        d = product_row(row)
        if d.get("category_id") and d.get("category_name"):
            d["category"] = {"id": d["category_id"], "name": d["category_name"]}
        else:
            d["category"] = None
        result.append(d)
    return jsonify(result)

@products_bp.route("/low-stock", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def low_stock():
    rows = query_db("SELECT * FROM products WHERE stock <= min_stock AND active=1 ORDER BY stock ASC")
    return jsonify([product_row(r) for r in rows])

@products_bp.route("/categories/", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def list_categories():
    rows = rows_to_dicts(query_db("SELECT * FROM categories ORDER BY name"))
    return jsonify(rows)

@products_bp.route("/categories/", methods=["POST"])
@require_role("admin", "manager")
def create_category():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Nome é obrigatório"}), 400
    cid = str(uuid.uuid4())
    execute_db("INSERT INTO categories (id, name, description) VALUES (?,?,?)",
               [cid, name, data.get("description")])
    cat = row_to_dict(query_db("SELECT * FROM categories WHERE id=?", [cid], one=True))
    return jsonify(cat), 201

@products_bp.route("/<product_id>", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def get_product(product_id):
    row = query_db("SELECT * FROM products WHERE id=?", [product_id], one=True)
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(product_row(row))

@products_bp.route("/", methods=["POST"])
@require_role("admin", "manager")
def create_product():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Nome é obrigatório"}), 400
    pid = str(uuid.uuid4())
    try:
        execute_db("""INSERT INTO products (id, name, description, sku, barcode, category_id,
                   cost_price, sale_price, stock, min_stock, unit) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                   [pid, name, data.get("description"), data.get("sku"),
                    data.get("barcode"), data.get("category_id"),
                    data.get("cost_price", 0), data.get("sale_price", 0),
                    data.get("stock", 0), data.get("min_stock", 0), data.get("unit", "un")])
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    row = query_db("SELECT * FROM products WHERE id=?", [pid], one=True)
    return jsonify(product_row(row)), 201

@products_bp.route("/<product_id>", methods=["PUT"])
@require_role("admin", "manager")
def update_product(product_id):
    data = request.get_json() or {}
    if "name" in data and not str(data.get("name") or "").strip():
        return jsonify({"error": "Nome é obrigatório"}), 400
    sets, vals = [], []
    for f in ["name", "description", "sku", "barcode", "category_id", "cost_price", "sale_price", "min_stock", "unit", "active"]:
        if f in data:
            sets.append(f"{f}=?")
            vals.append(data[f])
    if not sets:
        return jsonify({"error": "No data"}), 400
    vals.append(product_id)
    execute_db(f"UPDATE products SET {','.join(sets)} WHERE id=?", vals)
    row = query_db("SELECT * FROM products WHERE id=?", [product_id], one=True)
    return jsonify(product_row(row))

@products_bp.route("/<product_id>", methods=["DELETE"])
@require_role("admin")
def delete_product(product_id):
    execute_db("UPDATE products SET active=0 WHERE id=?", [product_id])
    return jsonify({"message": "Inativado"})
