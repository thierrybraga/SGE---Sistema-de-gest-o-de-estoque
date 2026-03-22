from flask import Blueprint, request, jsonify
from app.core.jwt_utils import require_role
from app.core.database import query_db, execute_db, row_to_dict, rows_to_dicts
import uuid

projects_bp = Blueprint("projects", __name__)

@projects_bp.route("/", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def list_projects():
    q = "SELECT * FROM projects WHERE 1=1"
    args = []
    if request.args.get("status"):
        q += " AND status=?"; args.append(request.args["status"])
    q += " ORDER BY created_at DESC"
    return jsonify(rows_to_dicts(query_db(q, args)))

@projects_bp.route("/", methods=["POST"])
@require_role("admin", "manager", "operator")
def create_project():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Nome é obrigatório"}), 400
    status = data.get("status") or "active"
    if status not in ("active", "completed", "cancelled"):
        return jsonify({"error": "Status inválido"}), 400
    pid = str(uuid.uuid4())
    execute_db("INSERT INTO projects (id, name, description, cost_center, status) VALUES (?,?,?,?,?)",
               [pid, name, data.get("description"), data.get("cost_center"), status])
    return jsonify(row_to_dict(query_db("SELECT * FROM projects WHERE id=?", [pid], one=True))), 201

@projects_bp.route("/<project_id>", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def get_project(project_id):
    row = query_db("SELECT * FROM projects WHERE id=?", [project_id], one=True)
    if not row: return jsonify({"error": "Not found"}), 404
    return jsonify(row_to_dict(row))

@projects_bp.route("/<project_id>", methods=["PUT"])
@require_role("admin", "manager", "operator")
def update_project(project_id):
    data = request.get_json() or {}
    sets, vals = [], []
    for f in ["name", "description", "cost_center", "status"]:
        if f in data:
            if f == "name":
                name = (data.get("name") or "").strip()
                if not name:
                    return jsonify({"error": "Nome é obrigatório"}), 400
                sets.append("name=?"); vals.append(name)
                continue
            if f == "status":
                status = data.get("status") or ""
                if status and status not in ("active", "completed", "cancelled"):
                    return jsonify({"error": "Status inválido"}), 400
            sets.append(f"{f}=?"); vals.append(data[f])
    if not sets:
        return jsonify({"error": "Nenhum campo para atualizar"}), 400
    vals.append(project_id)
    execute_db(f"UPDATE projects SET {','.join(sets)} WHERE id=?", vals)
    return jsonify(row_to_dict(query_db("SELECT * FROM projects WHERE id=?", [project_id], one=True)))

@projects_bp.route("/<project_id>/needs", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def get_needs(project_id):
    rows = query_db("""SELECT pn.*, p.name as product_name, p.sku as product_sku,
                       proj.name as project_name
                       FROM project_needs pn
                       LEFT JOIN products p ON pn.product_id = p.id
                       LEFT JOIN projects proj ON pn.project_id = proj.id
                       WHERE pn.project_id=?""", [project_id])
    result = []
    for row in rows:
        d = dict(row)
        d["quantity_missing"] = max(0, d["quantity_needed"] - d["quantity_reserved"])
        result.append(d)
    return jsonify(result)

@projects_bp.route("/<project_id>/needs", methods=["POST"])
@require_role("admin", "manager", "operator")
def add_need(project_id):
    data = request.get_json() or {}
    product_id = data.get("product_id")
    try:
        qty_needed = int(data.get("quantity_needed", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Quantidade inválida"}), 400
    if not product_id:
        return jsonify({"error": "Produto é obrigatório"}), 400
    if qty_needed <= 0:
        return jsonify({"error": "Quantidade inválida"}), 400
    nid = str(uuid.uuid4())
    execute_db("INSERT INTO project_needs (id, project_id, product_id, quantity_needed, observation) VALUES (?,?,?,?,?)",
               [nid, project_id, product_id, qty_needed, data.get("observation")])
    row = query_db("SELECT pn.*, p.name as product_name FROM project_needs pn LEFT JOIN products p ON pn.product_id=p.id WHERE pn.id=?", [nid], one=True)
    d = dict(row)
    d["quantity_missing"] = d["quantity_needed"]
    return jsonify(d), 201

@projects_bp.route("/<project_id>/match", methods=["POST"])
@require_role("admin", "manager")
def run_match(project_id):
    needs = query_db("SELECT * FROM project_needs WHERE project_id=?", [project_id])
    results = []
    for need in needs:
        need = dict(need)
        product = row_to_dict(query_db("SELECT * FROM products WHERE id=?", [need["product_id"]], one=True))
        if not product: continue
        available = product["stock"] - product["reserved_stock"]
        missing = max(0, need["quantity_needed"] - need["quantity_reserved"])
        can_reserve = min(missing, max(0, available))
        if can_reserve > 0:
            execute_db("UPDATE products SET reserved_stock=reserved_stock+? WHERE id=?", [can_reserve, product["id"]])
            new_reserved = need["quantity_reserved"] + can_reserve
            execute_db("UPDATE project_needs SET quantity_reserved=? WHERE id=?", [new_reserved, need["id"]])
            new_missing = max(0, need["quantity_needed"] - new_reserved)
            status = "fulfilled" if new_missing == 0 else "partial"
            execute_db("UPDATE project_needs SET status=? WHERE id=?", [status, need["id"]])
            results.append({"need_id": need["id"], "product_name": product["name"],
                            "needed": need["quantity_needed"], "reserved": new_reserved,
                            "missing": new_missing, "status": status})
        else:
            results.append({"need_id": need["id"], "product_name": product["name"],
                            "needed": need["quantity_needed"], "reserved": need["quantity_reserved"],
                            "missing": missing, "status": need["status"]})
    return jsonify({"results": results})
