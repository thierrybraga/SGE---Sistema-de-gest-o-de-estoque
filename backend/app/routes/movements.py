from flask import Blueprint, request, jsonify
from app.core.jwt_utils import require_role, get_current_user
from app.core.database import query_db, execute_db, row_to_dict, rows_to_dicts
import uuid

movements_bp = Blueprint("movements", __name__)

def mov_with_names(row):
    d = dict(row)
    return d

@movements_bp.route("/", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def list_movements():
    q = """SELECT m.*, p.name as product_name, u.name as user_name
           FROM movements m
           LEFT JOIN products p ON m.product_id = p.id
           LEFT JOIN users u ON m.user_id = u.id
           WHERE 1=1"""
    args = []
    if request.args.get("product_id"):
        q += " AND m.product_id=?"; args.append(request.args["product_id"])
    if request.args.get("type"):
        q += " AND m.type=?"; args.append(request.args["type"])
    if request.args.get("project_id"):
        q += " AND m.project_id=?"; args.append(request.args["project_id"])
    q += f" ORDER BY m.created_at DESC LIMIT {int(request.args.get('limit', 100))}"
    return jsonify(rows_to_dicts(query_db(q, args)))

@movements_bp.route("/entry", methods=["POST"])
@require_role("admin", "manager", "operator")
def entry():
    current = get_current_user()
    data = request.get_json() or {}
    product_id = data.get("product_id")
    if not product_id:
        return jsonify({"error": "Produto é obrigatório"}), 400
    try:
        qty = int(data.get("quantity", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Quantidade inválida"}), 400
    if qty <= 0:
        return jsonify({"error": "Quantidade inválida"}), 400
    product = row_to_dict(query_db("SELECT * FROM products WHERE id=? AND active=1", [product_id], one=True))
    if not product:
        return jsonify({"error": "Produto não encontrado"}), 400
    mid = str(uuid.uuid4())
    execute_db("""INSERT INTO movements (id, product_id, type, quantity, unit_cost, user_id, project_id, supplier_id, invoice_number, observation)
                  VALUES (?,?,?,?,?,?,?,?,?,?)""",
               [mid, product_id, "entry", qty, data.get("unit_cost", 0),
                current.get("id"), data.get("project_id"), data.get("supplier_id"),
                data.get("invoice_number"), data.get("observation")])
    execute_db("UPDATE products SET stock=stock+? WHERE id=?", [qty, product_id])
    return jsonify(row_to_dict(query_db("SELECT * FROM movements WHERE id=?", [mid], one=True))), 201

@movements_bp.route("/exit", methods=["POST"])
@require_role("admin", "manager", "operator")
def exit_stock():
    current = get_current_user()
    data = request.get_json() or {}
    product_id = data.get("product_id")
    if not product_id:
        return jsonify({"error": "Produto é obrigatório"}), 400
    try:
        qty = int(data.get("quantity", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Quantidade inválida"}), 400
    if qty <= 0:
        return jsonify({"error": "Quantidade inválida"}), 400
    product = row_to_dict(query_db("SELECT * FROM products WHERE id=? AND active=1", [product_id], one=True))
    if not product:
        return jsonify({"error": "Produto não encontrado"}), 400
    if product["stock"] < qty:
        return jsonify({"error": f"Estoque insuficiente. Disponível: {product['stock']}"}), 400
    mid = str(uuid.uuid4())
    execute_db("""INSERT INTO movements (id, product_id, type, quantity, unit_cost, user_id, project_id, supplier_id, invoice_number, observation)
                  VALUES (?,?,?,?,?,?,?,?,?,?)""",
               [mid, product_id, "exit", qty, data.get("unit_cost", 0),
                current.get("id"), data.get("project_id"), data.get("supplier_id"),
                data.get("invoice_number"), data.get("observation")])
    execute_db("UPDATE products SET stock=stock-? WHERE id=?", [qty, product_id])
    return jsonify(row_to_dict(query_db("SELECT * FROM movements WHERE id=?", [mid], one=True))), 201

@movements_bp.route("/adjustment", methods=["POST"])
@require_role("admin", "manager")
def adjustment():
    current = get_current_user()
    data = request.get_json() or {}
    if not data.get("observation"):
        return jsonify({"error": "Ajuste requer justificativa"}), 400
    product_id = data.get("product_id")
    if not product_id:
        return jsonify({"error": "Produto é obrigatório"}), 400
    try:
        new_qty = int(data.get("quantity", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Quantidade inválida"}), 400
    if new_qty < 0:
        return jsonify({"error": "Quantidade inválida"}), 400
    product = row_to_dict(query_db("SELECT * FROM products WHERE id=?", [product_id], one=True))
    if not product:
        return jsonify({"error": "Produto não encontrado"}), 400
    diff = new_qty - product["stock"]
    mid = str(uuid.uuid4())
    execute_db("""INSERT INTO movements (id, product_id, type, quantity, user_id, observation)
                  VALUES (?,?,?,?,?,?)""",
               [mid, product_id, "adjustment", diff, current.get("id"), data["observation"]])
    execute_db("UPDATE products SET stock=? WHERE id=?", [new_qty, product_id])
    return jsonify(row_to_dict(query_db("SELECT * FROM movements WHERE id=?", [mid], one=True))), 201
