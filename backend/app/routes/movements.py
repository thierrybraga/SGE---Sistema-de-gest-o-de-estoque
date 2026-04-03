from flask import Blueprint, request, jsonify
from app.core.jwt_utils import require_role, get_current_user
from app.core.database import query_db, execute_db, row_to_dict, rows_to_dicts, db_transaction
from app.core.audit import log_action
import uuid

movements_bp = Blueprint("movements", __name__)

def mov_with_names(row):
    d = dict(row)
    return d

@movements_bp.route("/", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def list_movements():
    q = """SELECT m.*, p.name as product_name, p.unit as product_unit,
                  u.name as user_name, u.role as user_role,
                  pr.name as project_name,
                  s.name as supplier_name,
                  inv.invoice_number as linked_invoice_number
           FROM movements m
           LEFT JOIN products p ON m.product_id = p.id
           LEFT JOIN users u ON m.user_id = u.id
           LEFT JOIN projects pr ON m.project_id = pr.id
           LEFT JOIN suppliers s ON m.supplier_id = s.id
           LEFT JOIN invoices inv ON m.invoice_id = inv.id
           WHERE 1=1"""
    args = []
    if request.args.get("product_id"):
        q += " AND m.product_id=?"; args.append(request.args["product_id"])
    if request.args.get("type"):
        q += " AND m.type=?"; args.append(request.args["type"])
    if request.args.get("project_id"):
        q += " AND m.project_id=?"; args.append(request.args["project_id"])
    if request.args.get("user_id"):
        q += " AND m.user_id=?"; args.append(request.args["user_id"])
    if request.args.get("supplier_id"):
        q += " AND m.supplier_id=?"; args.append(request.args["supplier_id"])
    if request.args.get("invoice_id"):
        q += " AND m.invoice_id=?"; args.append(request.args["invoice_id"])
    if request.args.get("date_from"):
        q += " AND date(m.created_at) >= date(?)"; args.append(request.args["date_from"])
    if request.args.get("date_to"):
        q += " AND date(m.created_at) <= date(?)"; args.append(request.args["date_to"])

    paginated = request.args.get("page") is not None

    if paginated:
        try:
            page = max(int(request.args.get("page", 1)), 1)
            per_page = min(int(request.args.get("per_page", 50)), 200)
        except (TypeError, ValueError):
            page, per_page = 1, 50

        count_q = q.replace(
            q[:q.index("FROM")],
            "SELECT COUNT(*) as total "
        )
        total = query_db(count_q, args, one=True)["total"]

        q += f" ORDER BY m.created_at DESC LIMIT {per_page} OFFSET {(page - 1) * per_page}"
        return jsonify({
            "data": rows_to_dicts(query_db(q, args)),
            "total": total, "page": page, "per_page": per_page,
            "pages": (total + per_page - 1) // per_page
        })

    # Legacy mode
    try:
        limit = min(int(request.args.get("limit", 200)), 1000)
        offset = max(int(request.args.get("offset", 0)), 0)
    except (TypeError, ValueError):
        limit, offset = 200, 0
    q += f" ORDER BY m.created_at DESC LIMIT {limit} OFFSET {offset}"
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
        qty = float(data.get("quantity", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Quantidade inválida"}), 400
    if qty <= 0:
        return jsonify({"error": "Quantidade deve ser maior que zero"}), 400
    product = row_to_dict(query_db("SELECT * FROM products WHERE id=? AND active=1", [product_id], one=True))
    if not product:
        return jsonify({"error": "Produto não encontrado"}), 400
    mid = str(uuid.uuid4())
    with db_transaction():
        execute_db("""INSERT INTO movements
                      (id, product_id, type, quantity, unit_cost, user_id, project_id, supplier_id,
                       invoice_number, invoice_id, invoice_item_id, observation)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                   [mid, product_id, "entry", qty,
                    float(data.get("unit_cost", 0) or 0),
                    current.get("id"),
                    data.get("project_id") or None,
                    data.get("supplier_id") or None,
                    data.get("invoice_number") or None,
                    data.get("invoice_id") or None,
                    data.get("invoice_item_id") or None,
                    data.get("observation") or None], commit=False)
        execute_db(
            "UPDATE products SET stock=stock+?, updated_at=datetime('now') WHERE id=?",
            [qty, product_id], commit=False
        )
    movement = row_to_dict(query_db("SELECT * FROM movements WHERE id=?", [mid], one=True))
    log_action("entry", "movement", entity_id=mid,
               details={"product_id": product_id, "product_name": product.get("name"),
                        "quantity": qty, "unit_cost": float(data.get("unit_cost", 0) or 0),
                        "invoice_number": data.get("invoice_number"),
                        "project_id": data.get("project_id")})
    return jsonify(movement), 201

@movements_bp.route("/exit", methods=["POST"])
@require_role("admin", "manager", "operator")
def exit_stock():
    current = get_current_user()
    data = request.get_json() or {}
    product_id = data.get("product_id")
    if not product_id:
        return jsonify({"error": "Produto é obrigatório"}), 400
    try:
        qty = float(data.get("quantity", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Quantidade inválida"}), 400
    if qty <= 0:
        return jsonify({"error": "Quantidade deve ser maior que zero"}), 400
    product = row_to_dict(query_db("SELECT * FROM products WHERE id=? AND active=1", [product_id], one=True))
    if not product:
        return jsonify({"error": "Produto não encontrado"}), 400
    available = float(product["stock"]) - float(product.get("reserved_stock", 0))
    if float(product["stock"]) < qty:
        return jsonify({"error": f"Estoque insuficiente. Disponível: {product['stock']}"}), 400

    # Check approval threshold
    approval_status = "approved"
    try:
        threshold_row = query_db("SELECT value FROM system_settings WHERE key='movement_approval_threshold'", one=True)
        threshold = float(threshold_row["value"]) if threshold_row and threshold_row["value"] else 0
        if threshold > 0 and qty >= threshold:
            user_role = current.get("role", "")
            if user_role not in ("admin", "manager"):
                approval_status = "pending"
    except Exception:
        pass

    mid = str(uuid.uuid4())
    with db_transaction():
        execute_db("""INSERT INTO movements
                      (id, product_id, type, quantity, unit_cost, user_id, project_id, supplier_id,
                       invoice_number, invoice_id, invoice_item_id, observation, approval_status)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   [mid, product_id, "exit", qty,
                    float(data.get("unit_cost", 0) or 0),
                    current.get("id"),
                    data.get("project_id") or None,
                    data.get("supplier_id") or None,
                    data.get("invoice_number") or None,
                    data.get("invoice_id") or None,
                    data.get("invoice_item_id") or None,
                    data.get("observation") or None,
                    approval_status], commit=False)
        if approval_status == "approved":
            execute_db(
                "UPDATE products SET stock=stock-?, updated_at=datetime('now') WHERE id=?",
                [qty, product_id], commit=False
            )
    movement = row_to_dict(query_db("SELECT * FROM movements WHERE id=?", [mid], one=True))
    log_action("exit", "movement", entity_id=mid,
               details={"product_id": product_id, "product_name": product.get("name"),
                        "quantity": qty, "project_id": data.get("project_id"),
                        "approval_status": approval_status})
    if approval_status == "pending":
        return jsonify({"message": "Saída requer aprovação de um gestor", "approval_status": "pending",
                        "movement": movement}), 201
    return jsonify(movement), 201

@movements_bp.route("/adjustment", methods=["POST"])
@require_role("admin", "manager")
def adjustment():
    current = get_current_user()
    data = request.get_json() or {}
    if not (data.get("observation") or "").strip():
        return jsonify({"error": "Ajuste requer justificativa obrigatória"}), 400
    product_id = data.get("product_id")
    if not product_id:
        return jsonify({"error": "Produto é obrigatório"}), 400
    try:
        new_qty = float(data.get("quantity", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Quantidade inválida"}), 400
    if new_qty < 0:
        return jsonify({"error": "Quantidade não pode ser negativa"}), 400
    product = row_to_dict(query_db("SELECT * FROM products WHERE id=? AND active=1", [product_id], one=True))
    if not product:
        return jsonify({"error": "Produto não encontrado"}), 400
    diff = new_qty - float(product["stock"])
    mid = str(uuid.uuid4())
    with db_transaction():
        execute_db(
            """INSERT INTO movements
               (id, product_id, type, quantity, unit_cost, user_id, observation)
               VALUES (?,?,?,?,?,?,?)""",
            [mid, product_id, "adjustment", diff, 0, current.get("id"), data["observation"]],
            commit=False
        )
        execute_db(
            "UPDATE products SET stock=?, updated_at=datetime('now') WHERE id=?",
            [new_qty, product_id], commit=False
        )
    movement = row_to_dict(query_db("SELECT * FROM movements WHERE id=?", [mid], one=True))
    log_action("adjustment", "movement", entity_id=mid,
               details={"product_id": product_id, "product_name": product.get("name"),
                        "old_stock": float(product["stock"]), "new_stock": new_qty,
                        "diff": diff, "observation": data["observation"]})
    return jsonify(movement), 201


@movements_bp.route("/pending-approval", methods=["GET"])
@require_role("admin", "manager")
def pending_approval():
    rows = query_db("""SELECT m.*, p.name as product_name, p.unit as product_unit,
                              u.name as user_name
                       FROM movements m
                       LEFT JOIN products p ON m.product_id = p.id
                       LEFT JOIN users u ON m.user_id = u.id
                       WHERE m.approval_status = 'pending'
                       ORDER BY m.created_at DESC""")
    return jsonify(rows_to_dicts(rows))


@movements_bp.route("/<movement_id>/approve", methods=["POST"])
@require_role("admin", "manager")
def approve_movement(movement_id):
    current = get_current_user()
    mov = query_db("SELECT * FROM movements WHERE id=? AND approval_status='pending'",
                   [movement_id], one=True)
    if not mov:
        return jsonify({"error": "Movimentação não encontrada ou já processada"}), 404
    mov = dict(mov)

    data = request.get_json() or {}
    with db_transaction():
        execute_db("""UPDATE movements SET approval_status='approved', approved_by=?,
                      approval_notes=? WHERE id=?""",
                   [current.get("id"), data.get("notes"), movement_id], commit=False)
        execute_db("UPDATE products SET stock=stock-?, updated_at=datetime('now') WHERE id=?",
                   [abs(mov["quantity"]), mov["product_id"]], commit=False)

    log_action("approve", "movement", entity_id=movement_id,
               details={"product_id": mov["product_id"], "quantity": mov["quantity"]})
    return jsonify({"message": "Movimentação aprovada e estoque atualizado"})


@movements_bp.route("/<movement_id>/reject", methods=["POST"])
@require_role("admin", "manager")
def reject_movement(movement_id):
    current = get_current_user()
    mov = query_db("SELECT * FROM movements WHERE id=? AND approval_status='pending'",
                   [movement_id], one=True)
    if not mov:
        return jsonify({"error": "Movimentação não encontrada ou já processada"}), 404

    data = request.get_json() or {}
    execute_db("""UPDATE movements SET approval_status='rejected', approved_by=?,
                  approval_notes=? WHERE id=?""",
               [current.get("id"), data.get("notes", "Rejeitado"), movement_id])

    log_action("reject", "movement", entity_id=movement_id,
               details={"product_id": dict(mov)["product_id"]})
    return jsonify({"message": "Movimentação rejeitada"})
