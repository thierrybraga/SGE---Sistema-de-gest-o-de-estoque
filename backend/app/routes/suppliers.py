from flask import Blueprint, request, jsonify
from app.core.jwt_utils import require_role
from app.core.database import query_db, execute_db, row_to_dict, rows_to_dicts
import uuid

suppliers_bp = Blueprint("suppliers", __name__)

@suppliers_bp.route("/", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def list_suppliers():
    return jsonify(rows_to_dicts(query_db("SELECT * FROM suppliers WHERE active=1 ORDER BY name")))

@suppliers_bp.route("/", methods=["POST"])
@require_role("admin", "manager", "buyer")
def create_supplier():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Nome é obrigatório"}), 400
    sid = str(uuid.uuid4())
    try:
        execute_db("INSERT INTO suppliers (id, name, cnpj, email, phone, address, contact_name, avg_lead_time) VALUES (?,?,?,?,?,?,?,?)",
                   [sid, name, data.get("cnpj"), data.get("email"), data.get("phone"),
                    data.get("address"), data.get("contact_name"), data.get("avg_lead_time", 7)])
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(row_to_dict(query_db("SELECT * FROM suppliers WHERE id=?", [sid], one=True))), 201

@suppliers_bp.route("/<supplier_id>", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def get_supplier(supplier_id):
    row = query_db("SELECT * FROM suppliers WHERE id=?", [supplier_id], one=True)
    if not row: return jsonify({"error": "Not found"}), 404
    return jsonify(row_to_dict(row))

@suppliers_bp.route("/<supplier_id>", methods=["PUT"])
@require_role("admin", "manager", "buyer")
def update_supplier(supplier_id):
    data = request.get_json() or {}
    if "name" in data and not str(data.get("name") or "").strip():
        return jsonify({"error": "Nome é obrigatório"}), 400
    sets, vals = [], []
    for f in ["name", "cnpj", "email", "phone", "address", "contact_name", "avg_lead_time", "rating", "active"]:
        if f in data:
            sets.append(f"{f}=?"); vals.append(data[f])
    if not sets:
        return jsonify({"error": "No data"}), 400
    vals.append(supplier_id)
    execute_db(f"UPDATE suppliers SET {','.join(sets)} WHERE id=?", vals)
    return jsonify(row_to_dict(query_db("SELECT * FROM suppliers WHERE id=?", [supplier_id], one=True)))

@suppliers_bp.route("/product-link", methods=["POST"])
@require_role("admin", "manager", "buyer")
def link_product():
    data = request.get_json() or {}
    if not data.get("product_id") or not data.get("supplier_id"):
        return jsonify({"error": "Produto e fornecedor são obrigatórios"}), 400
    lid = str(uuid.uuid4())
    execute_db("INSERT INTO product_suppliers (id, product_id, supplier_id, avg_price, lead_time, priority, notes) VALUES (?,?,?,?,?,?,?)",
               [lid, data["product_id"], data["supplier_id"], data.get("avg_price", 0),
                data.get("lead_time", 7), data.get("priority", 1), data.get("notes")])
    return jsonify(row_to_dict(query_db("SELECT * FROM product_suppliers WHERE id=?", [lid], one=True))), 201

@suppliers_bp.route("/product/<product_id>", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def product_suppliers(product_id):
    rows = query_db("""SELECT ps.*, s.name as supplier_name FROM product_suppliers ps
                       LEFT JOIN suppliers s ON ps.supplier_id = s.id
                       WHERE ps.product_id=? ORDER BY ps.priority""", [product_id])
    return jsonify(rows_to_dicts(rows))

@suppliers_bp.route("/quotations/", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def list_quotations():
    rows = query_db("""SELECT q.*, p.name as product_name FROM quotations q
                       LEFT JOIN products p ON q.product_id = p.id
                       ORDER BY q.created_at DESC""")
    result = []
    for row in rows:
        d = dict(row)
        items = rows_to_dicts(query_db("""SELECT qi.*, s.name as supplier_name FROM quotation_items qi
                              LEFT JOIN suppliers s ON qi.supplier_id = s.id
                              WHERE qi.quotation_id=?""", [d["id"]]))
        d["items"] = items
        result.append(d)
    return jsonify(result)

@suppliers_bp.route("/quotations/", methods=["POST"])
@require_role("admin", "manager", "buyer")
def create_quotation():
    data = request.get_json() or {}
    product_id = data.get("product_id")
    try:
        qty = int(data.get("quantity", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Quantidade inválida"}), 400
    if not product_id:
        return jsonify({"error": "Produto é obrigatório"}), 400
    if qty <= 0:
        return jsonify({"error": "Quantidade inválida"}), 400
    qid = str(uuid.uuid4())
    execute_db("INSERT INTO quotations (id, project_need_id, product_id, quantity, notes) VALUES (?,?,?,?,?)",
               [qid, data.get("project_need_id"), product_id, qty, data.get("notes")])
    # Auto-add linked suppliers
    linked = query_db("SELECT * FROM product_suppliers WHERE product_id=?", [product_id])
    for ps in linked:
        execute_db("INSERT INTO quotation_items (id, quotation_id, supplier_id, unit_price, lead_time) VALUES (?,?,?,?,?)",
                   [str(uuid.uuid4()), qid, ps["supplier_id"], ps["avg_price"], ps["lead_time"]])
    return jsonify(row_to_dict(query_db("SELECT * FROM quotations WHERE id=?", [qid], one=True))), 201

@suppliers_bp.route("/quotations/<quotation_id>/approve", methods=["POST"])
@require_role("admin", "manager")
def approve_quotation(quotation_id):
    data = request.get_json() or {}
    if not data.get("supplier_id"):
        return jsonify({"error": "Fornecedor é obrigatório"}), 400
    execute_db("UPDATE quotations SET status='approved', approved_supplier_id=? WHERE id=?",
               [data["supplier_id"], quotation_id])
    execute_db("UPDATE quotation_items SET status='approved' WHERE quotation_id=? AND supplier_id=?",
               [quotation_id, data["supplier_id"]])
    execute_db("UPDATE quotation_items SET status='rejected' WHERE quotation_id=? AND supplier_id!=?",
               [quotation_id, data["supplier_id"]])
    return jsonify(row_to_dict(query_db("SELECT * FROM quotations WHERE id=?", [quotation_id], one=True)))

@suppliers_bp.route("/quotation-items/<item_id>", methods=["PUT"])
@require_role("admin", "manager", "buyer")
def update_quotation_item(item_id):
    data = request.get_json() or {}
    sets, vals = [], []
    for f in ["unit_price", "lead_time", "notes", "status"]:
        if f in data:
            sets.append(f"{f}=?"); vals.append(data[f])
    if not sets:
        return jsonify({"error": "No data"}), 400
    vals.append(item_id)
    execute_db(f"UPDATE quotation_items SET {','.join(sets)} WHERE id=?", vals)
    item = row_to_dict(query_db("SELECT * FROM quotation_items WHERE id=?", [item_id], one=True))
    if item:
        qid = item.get("quotation_id")
        q = row_to_dict(query_db("SELECT status FROM quotations WHERE id=?", [qid], one=True))
        if q and q.get("status") == "open":
            has_prices = query_db(
                "SELECT 1 FROM quotation_items WHERE quotation_id=? AND unit_price>0 LIMIT 1",
                [qid],
                one=True,
            )
            if has_prices:
                execute_db("UPDATE quotations SET status='received' WHERE id=?", [qid])
    return jsonify(item)
