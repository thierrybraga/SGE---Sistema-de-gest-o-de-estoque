from flask import Blueprint, request, jsonify
from app.core.jwt_utils import require_role, get_current_user
from app.core.database import query_db, execute_db, row_to_dict, rows_to_dicts, db_transaction
from app.core.audit import log_action
import uuid

inventory_bp = Blueprint("inventory", __name__)


@inventory_bp.route("/sessions", methods=["GET"])
@require_role("admin", "manager")
def list_sessions():
    rows = query_db("""SELECT s.*, u.name as created_by_name,
                              (SELECT COUNT(*) FROM inventory_counts WHERE session_id=s.id) as items_count,
                              (SELECT COUNT(*) FROM inventory_counts WHERE session_id=s.id AND counted_quantity IS NOT NULL) as counted_count
                       FROM inventory_sessions s
                       LEFT JOIN users u ON s.created_by = u.id
                       ORDER BY s.created_at DESC""")
    return jsonify(rows_to_dicts(rows))


@inventory_bp.route("/sessions", methods=["POST"])
@require_role("admin", "manager")
def create_session():
    """Create a new inventory session and populate with current product quantities."""
    current = get_current_user()
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Nome da sessão é obrigatório"}), 400

    session_id = str(uuid.uuid4())
    warehouse_id = data.get("warehouse_id")
    category_id = data.get("category_id")

    with db_transaction():
        execute_db("""INSERT INTO inventory_sessions (id, name, status, warehouse_id, created_by, notes)
                      VALUES (?,?,?,?,?,?)""",
                   [session_id, name, "open", warehouse_id, current.get("id"),
                    data.get("notes")], commit=False)

        # Populate with active products
        where = "WHERE active=1"
        args = []
        if category_id:
            where += " AND category_id=?"
            args.append(category_id)

        products = query_db(f"SELECT id, stock FROM products {where}", args)
        for p in products:
            execute_db("""INSERT INTO inventory_counts
                          (id, session_id, product_id, system_quantity)
                          VALUES (?,?,?,?)""",
                       [str(uuid.uuid4()), session_id, p["id"], p["stock"]], commit=False)

    log_action("create", "inventory_session", entity_id=session_id,
               details={"name": name, "products_count": len(products)})
    return jsonify(row_to_dict(query_db("SELECT * FROM inventory_sessions WHERE id=?",
                                         [session_id], one=True))), 201


@inventory_bp.route("/sessions/<session_id>", methods=["GET"])
@require_role("admin", "manager", "operator")
def get_session(session_id):
    session = query_db("SELECT * FROM inventory_sessions WHERE id=?", [session_id], one=True)
    if not session:
        return jsonify({"error": "Sessão não encontrada"}), 404
    session = dict(session)
    counts = rows_to_dicts(query_db("""
        SELECT ic.*, p.name as product_name, p.sku as product_sku,
               p.category_id, c.name as category_name, p.unit as product_unit,
               u.name as counted_by_name
        FROM inventory_counts ic
        LEFT JOIN products p ON ic.product_id = p.id
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN users u ON ic.counted_by = u.id
        WHERE ic.session_id = ?
        ORDER BY p.name
    """, [session_id]))
    session["counts"] = counts
    session["total_items"] = len(counts)
    session["counted_items"] = len([c for c in counts if c["counted_quantity"] is not None])
    session["divergent_items"] = len([c for c in counts if c["difference"] and c["difference"] != 0])
    return jsonify(session)


@inventory_bp.route("/sessions/<session_id>/count", methods=["POST"])
@require_role("admin", "manager", "operator")
def record_count(session_id):
    """Record a physical count for a product in the session."""
    current = get_current_user()
    session = query_db("SELECT * FROM inventory_sessions WHERE id=? AND status IN ('open','counting')",
                       [session_id], one=True)
    if not session:
        return jsonify({"error": "Sessão não encontrada ou já fechada"}), 400

    data = request.get_json() or {}
    count_id = data.get("count_id")
    counted_qty = data.get("counted_quantity")

    if count_id is None or counted_qty is None:
        return jsonify({"error": "count_id e counted_quantity são obrigatórios"}), 400

    count = query_db("SELECT * FROM inventory_counts WHERE id=? AND session_id=?",
                     [count_id, session_id], one=True)
    if not count:
        return jsonify({"error": "Item não encontrado nesta sessão"}), 404

    counted_qty = float(counted_qty)
    difference = counted_qty - float(count["system_quantity"])

    execute_db("""UPDATE inventory_counts
                  SET counted_quantity=?, difference=?, counted_by=?,
                      notes=?, updated_at=datetime('now')
                  WHERE id=?""",
               [counted_qty, difference, current.get("id"),
                data.get("notes"), count_id])

    # Update session status to 'counting' if still open
    if dict(session)["status"] == "open":
        execute_db("UPDATE inventory_sessions SET status='counting' WHERE id=?", [session_id])

    return jsonify({"message": "Contagem registrada", "difference": difference})


@inventory_bp.route("/sessions/<session_id>/close", methods=["POST"])
@require_role("admin", "manager")
def close_session(session_id):
    """Close session and optionally apply adjustments."""
    current = get_current_user()
    session = query_db("SELECT * FROM inventory_sessions WHERE id=? AND status IN ('open','counting','review')",
                       [session_id], one=True)
    if not session:
        return jsonify({"error": "Sessão não encontrada ou já fechada"}), 400

    data = request.get_json() or {}
    apply_adjustments = data.get("apply_adjustments", False)
    adjustments_made = 0

    with db_transaction():
        if apply_adjustments:
            divergent = query_db("""SELECT * FROM inventory_counts
                                    WHERE session_id=? AND counted_quantity IS NOT NULL
                                    AND difference != 0 AND adjusted=0""", [session_id])
            for count in divergent:
                c = dict(count)
                mid = str(uuid.uuid4())
                execute_db("""INSERT INTO movements
                              (id, product_id, type, quantity, user_id, observation)
                              VALUES (?,?,?,?,?,?)""",
                           [mid, c["product_id"], "adjustment", c["difference"],
                            current.get("id"),
                            f"Ajuste de inventário — Sessão: {dict(session)['name']}"],
                           commit=False)
                new_stock = float(c["system_quantity"]) + float(c["difference"])
                execute_db("UPDATE products SET stock=?, updated_at=datetime('now') WHERE id=?",
                           [new_stock, c["product_id"]], commit=False)
                execute_db("UPDATE inventory_counts SET adjusted=1 WHERE id=?",
                           [c["id"]], commit=False)
                adjustments_made += 1

        execute_db("""UPDATE inventory_sessions
                      SET status='closed', closed_by=?, closed_at=datetime('now')
                      WHERE id=?""", [current.get("id"), session_id], commit=False)

    log_action("close", "inventory_session", entity_id=session_id,
               details={"adjustments": adjustments_made, "apply_adjustments": apply_adjustments})
    return jsonify({"message": f"Sessão encerrada. {adjustments_made} ajustes aplicados.",
                    "adjustments_made": adjustments_made})


# ===== WAREHOUSES =====

@inventory_bp.route("/warehouses", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def list_warehouses():
    rows = query_db("SELECT * FROM warehouses WHERE active=1 ORDER BY is_default DESC, name")
    return jsonify(rows_to_dicts(rows))


@inventory_bp.route("/warehouses", methods=["POST"])
@require_role("admin", "manager")
def create_warehouse():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Nome é obrigatório"}), 400
    wh_id = str(uuid.uuid4())
    execute_db("""INSERT INTO warehouses (id, name, code, address)
                  VALUES (?,?,?,?)""",
               [wh_id, name, data.get("code"), data.get("address")])
    log_action("create", "warehouse", entity_id=wh_id, details={"name": name})
    return jsonify(row_to_dict(query_db("SELECT * FROM warehouses WHERE id=?", [wh_id], one=True))), 201


@inventory_bp.route("/warehouses/<wh_id>", methods=["PUT"])
@require_role("admin", "manager")
def update_warehouse(wh_id):
    data = request.get_json() or {}
    sets, vals = [], []
    for f in ["name", "code", "address", "active"]:
        if f in data:
            sets.append(f"{f}=?")
            vals.append(data[f])
    if not sets:
        return jsonify({"error": "Nenhum dado"}), 400
    vals.append(wh_id)
    execute_db(f"UPDATE warehouses SET {','.join(sets)} WHERE id=?", vals)
    return jsonify(row_to_dict(query_db("SELECT * FROM warehouses WHERE id=?", [wh_id], one=True)))


# ===== PURCHASE FORECAST =====

@inventory_bp.route("/forecast", methods=["GET"])
@require_role("admin", "manager", "buyer")
def purchase_forecast():
    """Calculate purchase suggestions based on average consumption over last N months."""
    months = min(int(request.args.get("months", 3)), 12)
    days = months * 30

    rows = query_db("""
        SELECT p.id, p.name, p.sku, p.stock, p.min_stock, p.unit, p.cost_price,
               COALESCE(SUM(CASE WHEN m.type='exit' THEN m.quantity ELSE 0 END), 0) as total_consumed,
               COUNT(DISTINCT CASE WHEN m.type='exit' THEN date(m.created_at) END) as exit_days
        FROM products p
        LEFT JOIN movements m ON m.product_id = p.id
            AND m.type = 'exit'
            AND datetime(m.created_at) >= datetime('now', ?)
        WHERE p.active = 1
        GROUP BY p.id
        HAVING total_consumed > 0
        ORDER BY (total_consumed * 1.0 / ?) DESC
    """, (f"-{days} days", days))

    forecast = []
    for row in rows:
        d = dict(row)
        daily_avg = d["total_consumed"] / days if days > 0 else 0
        monthly_avg = daily_avg * 30
        days_until_empty = d["stock"] / daily_avg if daily_avg > 0 else 999
        days_until_min = (d["stock"] - d["min_stock"]) / daily_avg if daily_avg > 0 and d["stock"] > d["min_stock"] else 0
        suggested_qty = max(0, (monthly_avg * 2) - d["stock"] + d["min_stock"])

        if suggested_qty > 0:
            forecast.append({
                "product_id": d["id"],
                "name": d["name"],
                "sku": d["sku"],
                "unit": d["unit"],
                "current_stock": d["stock"],
                "min_stock": d["min_stock"],
                "monthly_avg_consumption": round(monthly_avg, 1),
                "daily_avg_consumption": round(daily_avg, 2),
                "days_until_empty": round(days_until_empty, 0),
                "days_until_min_stock": round(max(0, days_until_min), 0),
                "suggested_quantity": round(suggested_qty, 0),
                "estimated_cost": round(suggested_qty * (d["cost_price"] or 0), 2),
                "urgency": "critical" if days_until_empty <= 7 else "high" if days_until_empty <= 30 else "medium"
            })

    forecast.sort(key=lambda x: x["days_until_empty"])
    return jsonify(forecast)


# ===== ATTACHMENTS =====

@inventory_bp.route("/attachments/<entity_type>/<entity_id>", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def list_attachments(entity_type, entity_id):
    rows = query_db("""SELECT id, entity_type, entity_id, file_name, file_type, file_size,
                              description, uploaded_by, created_at
                       FROM attachments WHERE entity_type=? AND entity_id=?
                       ORDER BY created_at DESC""",
                    [entity_type, entity_id])
    return jsonify(rows_to_dicts(rows))


@inventory_bp.route("/attachments/<entity_type>/<entity_id>", methods=["POST"])
@require_role("admin", "manager", "operator", "buyer")
def upload_attachment(entity_type, entity_id):
    current = get_current_user()
    if "file" not in request.files:
        return jsonify({"error": "Arquivo não enviado"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Nome do arquivo inválido"}), 400

    # 10MB limit
    import base64
    file_data = file.read()
    if len(file_data) > 10 * 1024 * 1024:
        return jsonify({"error": "Arquivo muito grande (máx. 10MB)"}), 400

    att_id = str(uuid.uuid4())
    encoded = base64.b64encode(file_data).decode("utf-8")

    execute_db("""INSERT INTO attachments
                  (id, entity_type, entity_id, file_name, file_type, file_size,
                   file_data, description, uploaded_by)
                  VALUES (?,?,?,?,?,?,?,?,?)""",
               [att_id, entity_type, entity_id, file.filename,
                file.content_type, len(file_data), encoded,
                request.form.get("description"), current.get("id")])

    log_action("upload", "attachment", entity_id=att_id,
               details={"file_name": file.filename, "entity_type": entity_type,
                        "entity_id": entity_id})
    return jsonify({"id": att_id, "file_name": file.filename, "file_size": len(file_data)}), 201


@inventory_bp.route("/attachments/<att_id>/download", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def download_attachment(att_id):
    from flask import Response
    import base64
    att = query_db("SELECT * FROM attachments WHERE id=?", [att_id], one=True)
    if not att:
        return jsonify({"error": "Arquivo não encontrado"}), 404
    att = dict(att)
    file_data = base64.b64decode(att["file_data"])
    return Response(
        file_data,
        mimetype=att["file_type"] or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={att['file_name']}"}
    )


@inventory_bp.route("/attachments/<att_id>", methods=["DELETE"])
@require_role("admin", "manager")
def delete_attachment(att_id):
    att = query_db("SELECT * FROM attachments WHERE id=?", [att_id], one=True)
    if not att:
        return jsonify({"error": "Arquivo não encontrado"}), 404
    execute_db("DELETE FROM attachments WHERE id=?", [att_id])
    log_action("delete", "attachment", entity_id=att_id,
               details={"file_name": dict(att)["file_name"]})
    return jsonify({"message": "Arquivo removido"})


# ===== SYSTEM SETTINGS =====

@inventory_bp.route("/settings", methods=["GET"])
@require_role("admin")
def get_settings():
    rows = query_db("SELECT key, value FROM system_settings")
    settings = {r["key"]: r["value"] for r in rows}
    return jsonify(settings)


@inventory_bp.route("/settings", methods=["PUT"])
@require_role("admin")
def update_settings():
    data = request.get_json() or {}
    for key, value in data.items():
        execute_db("""INSERT INTO system_settings (key, value, updated_at)
                      VALUES (?, ?, datetime('now'))
                      ON CONFLICT(key) DO UPDATE SET value=?, updated_at=datetime('now')""",
                   [key, str(value), str(value)])
    log_action("update", "system_settings", details={"keys": list(data.keys())})
    return jsonify({"message": "Configurações atualizadas"})
