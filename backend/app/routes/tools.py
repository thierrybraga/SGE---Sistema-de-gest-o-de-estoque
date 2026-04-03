import csv
import io
import base64
import uuid
from datetime import datetime, date
from flask import Blueprint, request, jsonify, current_app
from app.core.jwt_utils import require_role, get_current_user
from app.core.database import query_db, execute_db, row_to_dict, rows_to_dicts, db_transaction
from app.core.audit import log_action

tools_bp = Blueprint("tools", __name__)

CONDITION_LABELS = {
    "new": "Novo",
    "good": "Bom",
    "regular": "Regular",
    "poor": "Ruim",
    "maintenance": "Manutenção",
}


def _tool_detail(tool_id):
    """Returns a tool row enriched with checkout stats."""
    tool = row_to_dict(query_db("SELECT * FROM tools WHERE id=?", [tool_id], one=True))
    if not tool:
        return None
    tool.pop("photo_base64", None)
    # Count active checkouts for this tool
    active = query_db(
        """SELECT SUM(tci.quantity - COALESCE(tci.returned_quantity,0)) as in_use
           FROM tool_checkout_items tci
           JOIN tool_checkouts tc ON tci.checkout_id = tc.id
           WHERE tci.tool_id=? AND tc.status IN ('active','renewed','overdue','partial')""",
        [tool_id], one=True
    )
    tool["units_in_use"] = int(active["in_use"] or 0) if active else 0
    return tool


def _sync_checkout_status(checkout_id):
    """Re-evaluates the checkout status based on items returned and due date."""
    checkout = row_to_dict(query_db("SELECT * FROM tool_checkouts WHERE id=?", [checkout_id], one=True))
    if not checkout or checkout["status"] == "returned":
        return
    items = rows_to_dicts(query_db(
        "SELECT quantity, returned_quantity FROM tool_checkout_items WHERE checkout_id=?",
        [checkout_id]
    ))
    total_qty = sum(i["quantity"] for i in items)
    total_returned = sum(i.get("returned_quantity") or 0 for i in items)

    if total_returned >= total_qty:
        new_status = "returned"
    elif total_returned > 0:
        new_status = "partial"
    elif checkout.get("expected_return_date"):
        try:
            due = datetime.strptime(checkout["expected_return_date"][:10], "%Y-%m-%d").date()
            new_status = "overdue" if date.today() > due else checkout["status"]
        except Exception:
            new_status = checkout["status"]
    else:
        new_status = checkout["status"]

    if new_status != checkout["status"]:
        execute_db(
            "UPDATE tool_checkouts SET status=?, updated_at=datetime('now') WHERE id=?",
            [new_status, checkout_id]
        )


# ─────────────────────────────────────────────────────────────
# Tools CRUD
# ─────────────────────────────────────────────────────────────

@tools_bp.route("/", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def list_tools():
    q = "SELECT * FROM tools WHERE 1=1"
    args = []
    if request.args.get("active", "1") != "all":
        q += " AND active=?"; args.append(int(request.args.get("active", 1)))
    if request.args.get("category"):
        q += " AND category=?"; args.append(request.args["category"])
    if request.args.get("condition"):
        q += " AND condition=?"; args.append(request.args["condition"])
    if request.args.get("q"):
        like = f"%{request.args['q']}%"
        q += " AND (name LIKE ? OR brand LIKE ? OR sku LIKE ?)"; args += [like, like, like]
    q += " ORDER BY name"
    rows = rows_to_dicts(query_db(q, args))
    # Strip large base64 from list view; add in-use count
    for tool in rows:
        tool.pop("photo_base64", None)
        active = query_db(
            """SELECT COALESCE(SUM(tci.quantity - COALESCE(tci.returned_quantity,0)),0) as in_use
               FROM tool_checkout_items tci
               JOIN tool_checkouts tc ON tci.checkout_id = tc.id
               WHERE tci.tool_id=? AND tc.status IN ('active','renewed','overdue','partial')""",
            [tool["id"]], one=True
        )
        tool["units_in_use"] = int(active["in_use"]) if active else 0
        tool["has_photo"] = False  # photo available via separate endpoint
    return jsonify(rows)


@tools_bp.route("/categories", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def list_tool_categories():
    rows = query_db("SELECT DISTINCT category FROM tools WHERE category IS NOT NULL AND category != '' ORDER BY category")
    return jsonify([r["category"] for r in rows])


@tools_bp.route("/", methods=["POST"])
@require_role("admin", "manager", "operator")
def create_tool():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Nome é obrigatório"}), 400
    try:
        total_units = int(data.get("total_units", 1))
        if total_units < 1:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Unidades deve ser um número inteiro positivo"}), 400
    min_units = max(int(data.get("min_units") or 0), 0)
    tid = str(uuid.uuid4())
    execute_db(
        """INSERT INTO tools
           (id, name, brand, sku, category, description, invoice_id, invoice_number,
            unit_value, total_units, available_units, min_units, condition, photo_base64)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [tid, name, data.get("brand"), data.get("sku") or None, data.get("category"),
         data.get("description"), data.get("invoice_id") or None, data.get("invoice_number") or None,
         float(data.get("unit_value") or 0), total_units, total_units, min_units,
         data.get("condition", "good"), data.get("photo_base64") or None]
    )
    tool = _tool_detail(tid)
    log_action("create", "tool", entity_id=tid,
               details={"name": name, "brand": data.get("brand"), "total_units": total_units})
    return jsonify(tool), 201


@tools_bp.route("/<tool_id>", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def get_tool(tool_id):
    include_photo = request.args.get("photo") == "1"
    tool = row_to_dict(query_db("SELECT * FROM tools WHERE id=?", [tool_id], one=True))
    if not tool:
        return jsonify({"error": "Ferramenta não encontrada"}), 404
    if not include_photo:
        tool.pop("photo_base64", None)
    # Recent checkouts
    tool["recent_checkouts"] = rows_to_dicts(query_db(
        """SELECT tc.id, tc.checkout_date, tc.expected_return_date, tc.status,
                  u.name as operator_name, tci.quantity, tci.returned_quantity
           FROM tool_checkout_items tci
           JOIN tool_checkouts tc ON tci.checkout_id = tc.id
           LEFT JOIN users u ON tc.operator_id = u.id
           WHERE tci.tool_id=?
           ORDER BY tc.checkout_date DESC LIMIT 10""",
        [tool_id]
    ))
    active = query_db(
        """SELECT COALESCE(SUM(tci.quantity - COALESCE(tci.returned_quantity,0)),0) as in_use
           FROM tool_checkout_items tci
           JOIN tool_checkouts tc ON tci.checkout_id = tc.id
           WHERE tci.tool_id=? AND tc.status IN ('active','renewed','overdue','partial')""",
        [tool_id], one=True
    )
    tool["units_in_use"] = int(active["in_use"]) if active else 0
    return jsonify(tool)


@tools_bp.route("/<tool_id>", methods=["PUT"])
@require_role("admin", "manager", "operator")
def update_tool(tool_id):
    tool = row_to_dict(query_db("SELECT * FROM tools WHERE id=?", [tool_id], one=True))
    if not tool:
        return jsonify({"error": "Ferramenta não encontrada"}), 404
    data = request.get_json() or {}
    current = get_current_user()
    actor_role = current.get("role", "")
    # Only admin/manager can change total_units (changes stock levels)
    if "total_units" in data and actor_role not in ("admin", "manager"):
        return jsonify({"error": "Sem permissão para alterar unidades totais"}), 403
    sets, vals = [], []
    for f in ["name", "brand", "sku", "category", "description", "invoice_id",
              "invoice_number", "unit_value", "min_units", "condition", "photo_base64"]:
        if f in data:
            sets.append(f"{f}=?"); vals.append(data[f])
    if "total_units" in data:
        try:
            new_total = int(data["total_units"])
            if new_total < 1:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "Unidades inválidas"}), 400
        old_total = tool["total_units"]
        diff = new_total - old_total
        sets.append("total_units=?"); vals.append(new_total)
        # Adjust available proportionally
        new_avail = max(0, tool["available_units"] + diff)
        sets.append("available_units=?"); vals.append(new_avail)
    if "active" in data and actor_role in ("admin", "manager"):
        sets.append("active=?"); vals.append(data["active"])
    if not sets:
        return jsonify({"error": "Nenhum dado enviado"}), 400
    sets.append("updated_at=datetime('now')")
    vals.append(tool_id)
    execute_db(f"UPDATE tools SET {','.join(sets)} WHERE id=?", vals)
    log_action("update", "tool", entity_id=tool_id,
               details={k: data[k] for k in data if k not in ("photo_base64",)})
    return jsonify(_tool_detail(tool_id))


@tools_bp.route("/<tool_id>/deactivate", methods=["POST"])
@require_role("admin", "manager")
def deactivate_tool(tool_id):
    tool = row_to_dict(query_db("SELECT id, name FROM tools WHERE id=?", [tool_id], one=True))
    if not tool:
        return jsonify({"error": "Ferramenta não encontrada"}), 404
    execute_db("UPDATE tools SET active=0, updated_at=datetime('now') WHERE id=?", [tool_id])
    log_action("deactivate", "tool", entity_id=tool_id, details={"name": tool.get("name")})
    return jsonify({"id": tool_id, "active": False})


@tools_bp.route("/<tool_id>/photo", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def get_tool_photo(tool_id):
    row = query_db("SELECT photo_base64 FROM tools WHERE id=?", [tool_id], one=True)
    if not row or not row["photo_base64"]:
        return jsonify({"error": "Sem foto cadastrada"}), 404
    return jsonify({"photo_base64": row["photo_base64"]})


# ─────────────────────────────────────────────────────────────
# CSV Import
# ─────────────────────────────────────────────────────────────

@tools_bp.route("/import-csv", methods=["POST"])
@require_role("admin")
def import_csv():
    """
    Bulk import tools from CSV.
    Expected columns (case-insensitive, first row is header):
      nome*, marca, sku, categoria, descricao, valor_unitario, total_unidades*, unidades_minimas, condicao
    """
    if "file" not in request.files:
        return jsonify({"error": "Arquivo CSV não enviado"}), 400
    f = request.files["file"]
    try:
        content = f.read().decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(content))
        # Normalize headers
        reader.fieldnames = [h.strip().lower().replace(" ", "_") for h in (reader.fieldnames or [])]
    except Exception as e:
        return jsonify({"error": f"Erro ao ler arquivo: {str(e)}"}), 400

    ALIASES = {
        "nome": "name", "name": "name",
        "marca": "brand", "brand": "brand", "vendor": "brand",
        "sku": "sku",
        "categoria": "category", "category": "category",
        "descricao": "description", "descricao_": "description", "description": "description",
        "valor_unitario": "unit_value", "valor": "unit_value", "value": "unit_value",
        "total_unidades": "total_units", "unidades": "total_units", "units": "total_units", "qtd": "total_units",
        "unidades_minimas": "min_units", "estoque_minimo": "min_units",
        "condicao": "condition", "condition": "condition",
        "numero_nota": "invoice_number", "nf": "invoice_number", "nota_fiscal": "invoice_number",
    }

    created, errors = [], []
    for i, row in enumerate(reader, start=2):  # row 1 = header
        mapped = {}
        for k, v in row.items():
            key = ALIASES.get(k.strip().lower())
            if key:
                mapped[key] = (v or "").strip()

        name = mapped.get("name", "").strip()
        if not name:
            errors.append({"row": i, "error": "Nome obrigatório"})
            continue
        try:
            total_units = int(mapped.get("total_units") or 1)
            if total_units < 1:
                raise ValueError
        except (TypeError, ValueError):
            errors.append({"row": i, "error": f"Unidades inválidas para '{name}'"})
            continue
        tid = str(uuid.uuid4())
        try:
            execute_db(
                """INSERT INTO tools
                   (id, name, brand, sku, category, description, invoice_number,
                    unit_value, total_units, available_units, min_units, condition)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                [tid, name,
                 mapped.get("brand") or None, mapped.get("sku") or None,
                 mapped.get("category") or None, mapped.get("description") or None,
                 mapped.get("invoice_number") or None,
                 float(mapped.get("unit_value") or 0),
                 total_units, total_units,
                 max(int(mapped.get("min_units") or 0), 0),
                 mapped.get("condition", "good")]
            )
            created.append({"id": tid, "name": name})
        except Exception as e:
            errors.append({"row": i, "name": name, "error": str(e)})

    log_action("import_csv", "tool", details={"created": len(created), "errors": len(errors)})
    return jsonify({"created": len(created), "errors": errors, "tools": created}), 201


# ─────────────────────────────────────────────────────────────
# Checkouts
# ─────────────────────────────────────────────────────────────

def _checkout_detail(checkout_id):
    co = row_to_dict(query_db(
        """SELECT tc.*,
                  u.name as operator_name, u.email as operator_email, u.role as operator_role,
                  cb.name as created_by_name,
                  p.name as project_name
           FROM tool_checkouts tc
           LEFT JOIN users u ON tc.operator_id = u.id
           LEFT JOIN users cb ON tc.created_by = cb.id
           LEFT JOIN projects p ON tc.project_id = p.id
           WHERE tc.id=?""",
        [checkout_id], one=True
    ))
    if not co:
        return None
    co.pop("checkout_photo", None)
    co.pop("return_photo", None)
    co["items"] = rows_to_dicts(query_db(
        """SELECT tci.*, t.name as tool_name, t.brand, t.sku, t.category, t.condition as tool_condition
           FROM tool_checkout_items tci
           LEFT JOIN tools t ON tci.tool_id = t.id
           WHERE tci.checkout_id=? ORDER BY tci.created_at""",
        [checkout_id]
    ))
    return co


@tools_bp.route("/checkouts/", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def list_checkouts():
    current = get_current_user()
    actor_role = current.get("role", "")
    q = """SELECT tc.*, u.name as operator_name, u.role as operator_role,
                  p.name as project_name,
                  (SELECT COUNT(*) FROM tool_checkout_items WHERE checkout_id=tc.id) as tool_count,
                  (SELECT COALESCE(SUM(quantity),0) FROM tool_checkout_items WHERE checkout_id=tc.id) as total_qty,
                  (SELECT COALESCE(SUM(returned_quantity),0) FROM tool_checkout_items WHERE checkout_id=tc.id) as returned_qty
           FROM tool_checkouts tc
           LEFT JOIN users u ON tc.operator_id = u.id
           LEFT JOIN projects p ON tc.project_id = p.id
           WHERE 1=1"""
    args = []
    # Operators only see their own checkouts
    if actor_role == "operator":
        q += " AND tc.operator_id=?"; args.append(current.get("id"))
    elif request.args.get("operator_id"):
        q += " AND tc.operator_id=?"; args.append(request.args["operator_id"])
    if request.args.get("status"):
        q += " AND tc.status=?"; args.append(request.args["status"])
    if request.args.get("tool_id"):
        q += " AND tc.id IN (SELECT checkout_id FROM tool_checkout_items WHERE tool_id=?)"
        args.append(request.args["tool_id"])
    if request.args.get("date_from"):
        q += " AND date(tc.checkout_date) >= date(?)"; args.append(request.args["date_from"])
    if request.args.get("date_to"):
        q += " AND date(tc.checkout_date) <= date(?)"; args.append(request.args["date_to"])
    try:
        limit = min(int(request.args.get("limit", 100)), 500)
        offset = max(int(request.args.get("offset", 0)), 0)
    except (TypeError, ValueError):
        limit, offset = 100, 0
    q += f" ORDER BY tc.checkout_date DESC LIMIT {limit} OFFSET {offset}"
    rows = rows_to_dicts(query_db(q, args))
    for row in rows:
        row.pop("checkout_photo", None)
        row.pop("return_photo", None)
    return jsonify(rows)


@tools_bp.route("/checkouts/", methods=["POST"])
@require_role("admin", "manager", "operator")
def create_checkout():
    """
    Creates a new tool checkout with one or more tools.
    Body:
    {
      "operator_id": "...",          # required (admin/manager set it; operator = self)
      "items": [                     # required, at least 1
        {"tool_id": "...", "quantity": 1}
      ],
      "expected_return_date": "YYYY-MM-DD",
      "project_id": "...",
      "observation": "...",
      "checkout_photo": "<base64>"   # optional
    }
    """
    current = get_current_user()
    actor_role = current.get("role", "")
    data = request.get_json() or {}

    # Resolve operator
    if actor_role == "operator":
        operator_id = current.get("id")
    else:
        operator_id = data.get("operator_id") or current.get("id")

    # Validate operator exists
    op = query_db("SELECT id, name FROM users WHERE id=? AND active=1", [operator_id], one=True)
    if not op:
        return jsonify({"error": "Operador não encontrado"}), 404

    items = data.get("items", [])
    if not items or not isinstance(items, list):
        return jsonify({"error": "Informe ao menos uma ferramenta"}), 400

    # Validate items and check availability
    validated_items = []
    for item in items:
        tool_id = item.get("tool_id")
        if not tool_id:
            return jsonify({"error": "tool_id obrigatório em cada item"}), 400
        try:
            qty = int(item.get("quantity", 1))
            if qty < 1:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "Quantidade inválida"}), 400
        tool = row_to_dict(query_db("SELECT * FROM tools WHERE id=? AND active=1", [tool_id], one=True))
        if not tool:
            return jsonify({"error": f"Ferramenta não encontrada ou inativa: {tool_id}"}), 404
        if tool["available_units"] < qty:
            return jsonify({
                "error": f"Unidades insuficientes para '{tool['name']}'. Disponível: {tool['available_units']}"
            }), 400
        validated_items.append((tool, qty))

    # Create checkout
    cid = str(uuid.uuid4())
    with db_transaction():
        execute_db(
            """INSERT INTO tool_checkouts
               (id, operator_id, project_id, checkout_date, expected_return_date,
                status, observation, checkout_photo, created_by)
               VALUES (?,?,?,datetime('now'),?,?,?,?,?)""",
            [cid, operator_id, data.get("project_id") or None,
             data.get("expected_return_date") or None,
             "active", data.get("observation") or None,
             data.get("checkout_photo") or None, current.get("id")],
            commit=False
        )
        for tool, qty in validated_items:
            execute_db(
                """INSERT INTO tool_checkout_items
                   (id, checkout_id, tool_id, quantity)
                   VALUES (?,?,?,?)""",
                [str(uuid.uuid4()), cid, tool["id"], qty],
                commit=False
            )
            execute_db(
                "UPDATE tools SET available_units=available_units-?, updated_at=datetime('now') WHERE id=?",
                [qty, tool["id"]], commit=False
            )

    detail = _checkout_detail(cid)
    tool_names = [t["name"] for t, _ in validated_items]
    log_action("checkout", "tool_checkout", entity_id=cid,
               details={"operator_id": operator_id, "operator_name": op["name"],
                        "tools": tool_names, "qty_total": sum(q for _, q in validated_items)})
    return jsonify(detail), 201


@tools_bp.route("/checkouts/<checkout_id>", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def get_checkout(checkout_id):
    current = get_current_user()
    actor_role = current.get("role", "")
    co = _checkout_detail(checkout_id)
    if not co:
        return jsonify({"error": "Retirada não encontrada"}), 404
    if actor_role == "operator" and co.get("operator_id") != current.get("id"):
        return jsonify({"error": "Sem permissão para visualizar esta retirada"}), 403
    # Include photos if requested
    if request.args.get("photos") == "1":
        row = query_db("SELECT checkout_photo, return_photo FROM tool_checkouts WHERE id=?", [checkout_id], one=True)
        if row:
            co["checkout_photo"] = row["checkout_photo"]
            co["return_photo"] = row["return_photo"]
    return jsonify(co)


@tools_bp.route("/checkouts/<checkout_id>/return", methods=["POST"])
@require_role("admin", "manager", "operator")
def return_checkout(checkout_id):
    """
    Records return of tools. Can be partial.
    Body:
    {
      "items": [
        {"item_id": "...", "returned_quantity": 2, "condition_on_return": "good", "observation": "..."}
      ],
      "return_photo": "<base64>",
      "observation": "..."
    }
    """
    current = get_current_user()
    actor_role = current.get("role", "")
    co = row_to_dict(query_db("SELECT * FROM tool_checkouts WHERE id=?", [checkout_id], one=True))
    if not co:
        return jsonify({"error": "Retirada não encontrada"}), 404
    if actor_role == "operator" and co.get("operator_id") != current.get("id"):
        return jsonify({"error": "Sem permissão"}), 403
    if co["status"] == "returned":
        return jsonify({"error": "Esta retirada já foi devolvida completamente"}), 400

    data = request.get_json() or {}
    items_data = data.get("items", [])
    if not items_data:
        return jsonify({"error": "Informe os itens a devolver"}), 400

    with db_transaction():
        for item_in in items_data:
            item_id   = item_in.get("item_id")
            tool_id_r = item_in.get("tool_id")
            if item_id:
                item = row_to_dict(query_db(
                    "SELECT * FROM tool_checkout_items WHERE id=? AND checkout_id=?",
                    [item_id, checkout_id], one=True
                ))
            elif tool_id_r:
                item = row_to_dict(query_db(
                    "SELECT * FROM tool_checkout_items WHERE tool_id=? AND checkout_id=?",
                    [tool_id_r, checkout_id], one=True
                ))
            else:
                continue
            if not item:
                continue
            item_id = item["id"]
            try:
                ret_qty = int(item_in.get("returned_quantity", 0))
                if ret_qty < 0:
                    ret_qty = 0
            except (TypeError, ValueError):
                ret_qty = 0
            already_returned = item.get("returned_quantity") or 0
            remaining = item["quantity"] - already_returned
            ret_qty = min(ret_qty, remaining)
            if ret_qty <= 0:
                continue
            new_returned = already_returned + ret_qty
            execute_db(
                """UPDATE tool_checkout_items
                   SET returned_quantity=?, condition_on_return=?, observation=?,
                       returned_at=COALESCE(returned_at, datetime('now'))
                   WHERE id=?""",
                [new_returned, item_in.get("condition_on_return") or item.get("condition_on_return"),
                 item_in.get("observation"), item_id],
                commit=False
            )
            execute_db(
                "UPDATE tools SET available_units=available_units+?, updated_at=datetime('now') WHERE id=?",
                [ret_qty, item["tool_id"]], commit=False
            )

        if data.get("return_photo") or data.get("observation"):
            sets, vals = [], []
            if data.get("return_photo"):
                sets.append("return_photo=?"); vals.append(data["return_photo"])
            if data.get("observation"):
                sets.append("observation=COALESCE(observation||' | ','')||?"); vals.append(data["observation"])
            if sets:
                vals.append(checkout_id)
                execute_db(f"UPDATE tool_checkouts SET {','.join(sets)},updated_at=datetime('now') WHERE id=?", vals, commit=False)

        # Update actual return date if not set
        execute_db(
            "UPDATE tool_checkouts SET actual_return_date=COALESCE(actual_return_date,datetime('now')),updated_at=datetime('now') WHERE id=?",
            [checkout_id], commit=False
        )

    _sync_checkout_status(checkout_id)
    detail = _checkout_detail(checkout_id)
    log_action("return", "tool_checkout", entity_id=checkout_id,
               details={"operator_id": co.get("operator_id"), "items_returned": len(items_data)})
    return jsonify(detail)


@tools_bp.route("/checkouts/<checkout_id>/renew", methods=["POST"])
@require_role("admin", "manager", "operator")
def renew_checkout(checkout_id):
    """Extends the expected_return_date of an active checkout."""
    current = get_current_user()
    actor_role = current.get("role", "")
    co = row_to_dict(query_db("SELECT * FROM tool_checkouts WHERE id=?", [checkout_id], one=True))
    if not co:
        return jsonify({"error": "Retirada não encontrada"}), 404
    if actor_role == "operator" and co.get("operator_id") != current.get("id"):
        return jsonify({"error": "Sem permissão"}), 403
    if co["status"] == "returned":
        return jsonify({"error": "Não é possível renovar uma retirada já devolvida"}), 400

    data = request.get_json() or {}
    new_date = data.get("new_return_date")
    if not new_date:
        return jsonify({"error": "Informe a nova data de devolução (new_return_date)"}), 400
    try:
        datetime.strptime(new_date[:10], "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "Data inválida. Use o formato YYYY-MM-DD"}), 400

    execute_db(
        """UPDATE tool_checkouts
           SET expected_return_date=?, status=CASE WHEN status='returned' THEN 'returned' ELSE 'renewed' END,
               renewed_count=renewed_count+1, updated_at=datetime('now')
           WHERE id=?""",
        [new_date, checkout_id]
    )
    _sync_checkout_status(checkout_id)
    detail = _checkout_detail(checkout_id)
    log_action("renew", "tool_checkout", entity_id=checkout_id,
               details={"new_return_date": new_date, "renewed_count": (co.get("renewed_count") or 0) + 1})
    return jsonify(detail)


# ─────────────────────────────────────────────────────────────
# Reports
# ─────────────────────────────────────────────────────────────

@tools_bp.route("/report/summary", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def report_summary():
    """Global dashboard stats."""
    stats = {}
    stats["total_tools"] = query_db("SELECT COUNT(*) as c FROM tools WHERE active=1", one=True)["c"]
    stats["total_units"] = query_db("SELECT COALESCE(SUM(total_units),0) as s FROM tools WHERE active=1", one=True)["s"]
    stats["available_units"] = query_db("SELECT COALESCE(SUM(available_units),0) as s FROM tools WHERE active=1", one=True)["s"]
    stats["units_in_use"] = stats["total_units"] - stats["available_units"]
    stats["total_value"] = query_db(
        "SELECT COALESCE(SUM(unit_value * total_units),0) as s FROM tools WHERE active=1", one=True
    )["s"]
    stats["value_in_use"] = query_db(
        """SELECT COALESCE(SUM(t.unit_value * (t.total_units - t.available_units)),0) as s
           FROM tools t WHERE t.active=1 AND t.total_units > t.available_units""",
        one=True
    )["s"]
    stats["active_checkouts"] = query_db(
        "SELECT COUNT(*) as c FROM tool_checkouts WHERE status IN ('active','renewed','partial')", one=True
    )["c"]
    stats["overdue_checkouts"] = query_db(
        "SELECT COUNT(*) as c FROM tool_checkouts WHERE status='overdue'", one=True
    )["c"]
    # Critical: tools where available_units <= min_units
    stats["critical_tools"] = query_db(
        "SELECT COUNT(*) as c FROM tools WHERE active=1 AND min_units > 0 AND available_units <= min_units", one=True
    )["c"]
    stats["missing_tools"] = query_db(
        "SELECT COUNT(*) as c FROM tools WHERE active=1 AND available_units = 0 AND total_units > 0", one=True
    )["c"]

    # Critical tools list
    stats["critical_list"] = rows_to_dicts(query_db(
        """SELECT id, name, brand, available_units, total_units, min_units, condition
           FROM tools WHERE active=1 AND min_units > 0 AND available_units <= min_units
           ORDER BY (available_units * 1.0 / total_units) ASC LIMIT 10""",
    ))

    # Top overdue checkouts
    stats["overdue_list"] = rows_to_dicts(query_db(
        """SELECT tc.id, tc.checkout_date, tc.expected_return_date, u.name as operator_name,
                  (SELECT GROUP_CONCAT(t.name, ', ') FROM tool_checkout_items tci
                   JOIN tools t ON tci.tool_id = t.id WHERE tci.checkout_id = tc.id) as tools_list
           FROM tool_checkouts tc
           LEFT JOIN users u ON tc.operator_id = u.id
           WHERE tc.status='overdue'
           ORDER BY tc.expected_return_date ASC LIMIT 10"""
    ))
    return jsonify(stats)


@tools_bp.route("/report/by-operator", methods=["GET"])
@require_role("admin", "manager")
def report_by_operator():
    """Returns tool usage grouped by operator."""
    rows = rows_to_dicts(query_db(
        """SELECT u.id as operator_id, u.name as operator_name, u.email, u.role,
                  COUNT(DISTINCT tc.id) as total_checkouts,
                  SUM(CASE WHEN tc.status IN ('active','renewed','overdue','partial') THEN 1 ELSE 0 END) as active_checkouts,
                  SUM(CASE WHEN tc.status='overdue' THEN 1 ELSE 0 END) as overdue_checkouts,
                  COALESCE(SUM(tci.quantity),0) as total_tools_taken,
                  COALESCE(SUM(tci.returned_quantity),0) as total_returned,
                  MAX(tc.checkout_date) as last_checkout_date
           FROM tool_checkouts tc
           JOIN users u ON tc.operator_id = u.id
           JOIN tool_checkout_items tci ON tci.checkout_id = tc.id
           GROUP BY u.id ORDER BY active_checkouts DESC, last_checkout_date DESC"""
    ))
    return jsonify(rows)


@tools_bp.route("/report/operator/<operator_id>", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def report_operator_detail(operator_id):
    """All checkouts and tool detail for a specific operator."""
    current = get_current_user()
    actor_role = current.get("role", "")
    if actor_role == "operator" and current.get("id") != operator_id:
        return jsonify({"error": "Sem permissão"}), 403

    op = row_to_dict(query_db("SELECT id, name, email, role FROM users WHERE id=?", [operator_id], one=True))
    if not op:
        return jsonify({"error": "Operador não encontrado"}), 404

    q = """SELECT tc.id, tc.checkout_date, tc.expected_return_date, tc.actual_return_date,
                  tc.status, tc.observation, tc.renewed_count, p.name as project_name,
                  (SELECT GROUP_CONCAT(t.name||' (x'||tci.quantity||')', ', ')
                   FROM tool_checkout_items tci JOIN tools t ON tci.tool_id=t.id
                   WHERE tci.checkout_id=tc.id) as tools_summary
           FROM tool_checkouts tc
           LEFT JOIN projects p ON tc.project_id = p.id
           WHERE tc.operator_id=?"""
    args = [operator_id]
    if request.args.get("status"):
        q += " AND tc.status=?"; args.append(request.args["status"])
    if request.args.get("date_from"):
        q += " AND date(tc.checkout_date) >= date(?)"; args.append(request.args["date_from"])
    if request.args.get("date_to"):
        q += " AND date(tc.checkout_date) <= date(?)"; args.append(request.args["date_to"])
    q += " ORDER BY tc.checkout_date DESC"
    checkouts = rows_to_dicts(query_db(q, args))

    # Current tools with this operator
    current_tools = rows_to_dicts(query_db(
        """SELECT t.id, t.name, t.brand, t.sku, t.category, t.unit_value,
                  SUM(tci.quantity - COALESCE(tci.returned_quantity,0)) as qty_with_operator,
                  MIN(tc.checkout_date) as since_date,
                  MAX(tc.expected_return_date) as latest_due_date
           FROM tool_checkout_items tci
           JOIN tool_checkouts tc ON tci.checkout_id = tc.id
           JOIN tools t ON tci.tool_id = t.id
           WHERE tc.operator_id=? AND tc.status IN ('active','renewed','overdue','partial')
             AND (tci.quantity - COALESCE(tci.returned_quantity,0)) > 0
           GROUP BY t.id""",
        [operator_id]
    ))
    return jsonify({"operator": op, "checkouts": checkouts, "current_tools": current_tools})
