from flask import Blueprint, request, jsonify
from app.core.jwt_utils import require_role, get_current_user
from app.core.database import query_db, execute_db, row_to_dict, rows_to_dicts, db_transaction
from app.core.audit import log_action
import uuid
import csv
import io

projects_bp = Blueprint("projects", __name__)

@projects_bp.route("/", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def list_projects():
    q = """
        SELECT p.*, u.name as manager_name
        FROM projects p
        LEFT JOIN users u ON p.manager_id = u.id
        WHERE 1=1
    """
    args = []
    if request.args.get("status"):
        q += " AND p.status=?"; args.append(request.args["status"])
    q += " ORDER BY p.created_at DESC"
    rows = query_db(q, args)
    result = []
    for row in rows:
        d = dict(row)
        r1 = query_db("SELECT COUNT(*) as c FROM project_needs WHERE project_id=?", [d["id"]], one=True)
        d["needs_count"] = r1["c"] if r1 else 0
        r2 = query_db(
            "SELECT COUNT(*) as c FROM project_needs WHERE project_id=? AND status IN ('pending','partial')",
            [d["id"]], one=True
        )
        d["pending_needs"] = r2["c"] if r2 else 0
        result.append(d)
    return jsonify(result)

@projects_bp.route("/", methods=["POST"])
@require_role("admin", "manager")
def create_project():
    current = get_current_user()
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Nome é obrigatório"}), 400
    status = data.get("status") or "active"
    if status not in ("active", "completed", "cancelled"):
        return jsonify({"error": "Status inválido"}), 400
    pid = str(uuid.uuid4())
    execute_db(
        "INSERT INTO projects (id, name, description, cost_center, manager_id, status, start_date) VALUES (?,?,?,?,?,?,date('now'))",
        [pid, name, data.get("description") or None, data.get("cost_center") or None,
         current.get("id"), status]
    )
    proj = row_to_dict(query_db("SELECT * FROM projects WHERE id=?", [pid], one=True))
    log_action("create", "project", entity_id=pid,
               details={"name": name, "status": status, "cost_center": data.get("cost_center")})
    return jsonify(proj), 201

@projects_bp.route("/<project_id>", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def get_project(project_id):
    row = query_db(
        "SELECT p.*, u.name as manager_name FROM projects p LEFT JOIN users u ON p.manager_id=u.id WHERE p.id=?",
        [project_id], one=True
    )
    if not row: return jsonify({"error": "Projeto não encontrado"}), 404
    return jsonify(row_to_dict(row))

@projects_bp.route("/<project_id>", methods=["PUT"])
@require_role("admin", "manager")
def update_project(project_id):
    data = request.get_json() or {}
    sets, vals = [], []
    for f in ["name", "description", "cost_center", "status", "end_date"]:
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
    sets.append("updated_at=datetime('now')")
    vals.append(project_id)
    execute_db(f"UPDATE projects SET {','.join(sets)} WHERE id=?", vals)
    proj = row_to_dict(query_db("SELECT * FROM projects WHERE id=?", [project_id], one=True))
    log_action("update", "project", entity_id=project_id,
               details={k: data[k] for k in ["name","description","status","cost_center","end_date"] if k in data})
    return jsonify(proj)

@projects_bp.route("/<project_id>", methods=["DELETE"])
@require_role("admin", "manager")
def delete_project(project_id):
    proj = row_to_dict(query_db("SELECT id, name FROM projects WHERE id=?", [project_id], one=True))
    if not proj:
        return jsonify({"error": "Projeto não encontrado"}), 404
    # Release all reserved stock for this project's needs
    needs = rows_to_dicts(query_db(
        "SELECT product_id, quantity_reserved FROM project_needs WHERE project_id=? AND quantity_reserved > 0",
        [project_id]
    ))
    for n in needs:
        reserved = float(n.get("quantity_reserved", 0))
        if reserved > 0:
            execute_db(
                "UPDATE products SET reserved_stock=CASE WHEN reserved_stock-? < 0 THEN 0 ELSE reserved_stock-? END, updated_at=datetime('now') WHERE id=?",
                [reserved, reserved, n["product_id"]]
            )
    execute_db("DELETE FROM project_needs WHERE project_id=?", [project_id])
    execute_db("DELETE FROM projects WHERE id=?", [project_id])
    log_action("delete", "project", entity_id=project_id,
               details={"name": proj.get("name"), "needs_released": len(needs)})
    return jsonify({"message": "Projeto removido"})

@projects_bp.route("/<project_id>/needs", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def get_needs(project_id):
    rows = query_db("""
        SELECT pn.*,
               p.name as product_name, p.sku as product_sku, p.unit as product_unit,
               p.stock as product_stock, p.reserved_stock as product_reserved,
               proj.name as project_name
        FROM project_needs pn
        LEFT JOIN products p ON pn.product_id = p.id
        LEFT JOIN projects proj ON pn.project_id = proj.id
        WHERE pn.project_id=?
        ORDER BY pn.created_at ASC
    """, [project_id])
    result = []
    for row in rows:
        d = dict(row)
        d["quantity_missing"] = max(0, float(d["quantity_needed"]) - float(d["quantity_reserved"]))
        d["product_available"] = max(0, float(d.get("product_stock", 0)) - float(d.get("product_reserved", 0)))
        result.append(d)
    return jsonify(result)

@projects_bp.route("/<project_id>/needs", methods=["POST"])
@require_role("admin", "manager")
def add_need(project_id):
    data = request.get_json() or {}
    product_id = data.get("product_id")
    if not product_id:
        return jsonify({"error": "Produto é obrigatório"}), 400
    # Validate project exists
    project = query_db("SELECT id FROM projects WHERE id=?", [project_id], one=True)
    if not project:
        return jsonify({"error": "Projeto não encontrado"}), 404
    # Validate product exists and is active
    product = query_db("SELECT id, name, unit FROM products WHERE id=? AND active=1", [product_id], one=True)
    if not product:
        return jsonify({"error": "Produto não encontrado ou inativo"}), 400
    try:
        qty_needed = float(data.get("quantity_needed", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Quantidade inválida"}), 400
    if qty_needed <= 0:
        return jsonify({"error": "Quantidade deve ser maior que zero"}), 400
    # Check for duplicate (same project + product)
    existing = query_db(
        "SELECT id FROM project_needs WHERE project_id=? AND product_id=?",
        [project_id, product_id], one=True
    )
    if existing:
        return jsonify({"error": "Este produto já foi adicionado às necessidades deste projeto. Edite a necessidade existente."}), 400
    nid = str(uuid.uuid4())
    execute_db(
        "INSERT INTO project_needs (id, project_id, product_id, quantity_needed, observation) VALUES (?,?,?,?,?)",
        [nid, project_id, product_id, qty_needed, data.get("observation") or None]
    )
    row = query_db("""
        SELECT pn.*, p.name as product_name, p.sku as product_sku, p.unit as product_unit,
               p.stock as product_stock, p.reserved_stock as product_reserved
        FROM project_needs pn
        LEFT JOIN products p ON pn.product_id=p.id
        WHERE pn.id=?
    """, [nid], one=True)
    d = dict(row)
    d["quantity_missing"] = float(d["quantity_needed"])
    d["product_available"] = max(0, float(d.get("product_stock", 0)) - float(d.get("product_reserved", 0)))
    log_action("create", "project_need", entity_id=nid,
               details={"project_id": project_id, "product_id": product_id,
                        "product_name": d.get("product_name"), "quantity_needed": qty_needed})
    return jsonify(d), 201

@projects_bp.route("/<project_id>/needs/<need_id>", methods=["PUT"])
@require_role("admin", "manager")
def update_need(project_id, need_id):
    data = request.get_json() or {}
    need = query_db("SELECT * FROM project_needs WHERE id=? AND project_id=?", [need_id, project_id], one=True)
    if not need:
        return jsonify({"error": "Necessidade não encontrada"}), 404
    sets, vals = [], []
    if "quantity_needed" in data:
        try:
            qty = float(data["quantity_needed"])
            if qty <= 0:
                return jsonify({"error": "Quantidade deve ser maior que zero"}), 400
        except (TypeError, ValueError):
            return jsonify({"error": "Quantidade inválida"}), 400
        sets.append("quantity_needed=?"); vals.append(qty)
    if "observation" in data:
        sets.append("observation=?"); vals.append(data["observation"] or None)
    if not sets:
        return jsonify({"error": "Nenhum campo para atualizar"}), 400
    sets.append("updated_at=datetime('now')")
    vals.append(need_id)
    execute_db(f"UPDATE project_needs SET {','.join(sets)} WHERE id=?", vals)
    row = query_db("""
        SELECT pn.*, p.name as product_name, p.sku as product_sku, p.unit as product_unit
        FROM project_needs pn LEFT JOIN products p ON pn.product_id=p.id WHERE pn.id=?
    """, [need_id], one=True)
    d = dict(row)
    d["quantity_missing"] = max(0, float(d["quantity_needed"]) - float(d["quantity_reserved"]))
    log_action("update", "project_need", entity_id=need_id,
               details={"project_id": project_id, "changes": {k: data[k] for k in data}})
    return jsonify(d)

@projects_bp.route("/<project_id>/needs/<need_id>", methods=["DELETE"])
@require_role("admin", "manager")
def delete_need(project_id, need_id):
    need = query_db("SELECT * FROM project_needs WHERE id=? AND project_id=?", [need_id, project_id], one=True)
    if not need:
        return jsonify({"error": "Necessidade não encontrada"}), 404
    need = dict(need)
    # Release any reserved stock for this need
    reserved = float(need.get("quantity_reserved", 0))
    if reserved > 0:
        execute_db(
            "UPDATE products SET reserved_stock=CASE WHEN reserved_stock-? < 0 THEN 0 ELSE reserved_stock-? END, updated_at=datetime('now') WHERE id=?",
            [reserved, reserved, need["product_id"]]
        )
    execute_db("DELETE FROM project_needs WHERE id=?", [need_id])
    log_action("delete", "project_need", entity_id=need_id,
               details={"project_id": project_id, "product_id": need.get("product_id"),
                        "reserved_released": reserved})
    return jsonify({"message": "Necessidade removida e estoque reservado liberado"})

@projects_bp.route("/<project_id>/needs/import/csv", methods=["POST"])
@require_role("admin", "manager")
def import_needs_csv(project_id):
    project = query_db("SELECT id FROM projects WHERE id=?", [project_id], one=True)
    if not project:
        return jsonify({"error": "Projeto não encontrado"}), 404

    if "file" not in request.files:
        return jsonify({"error": "Arquivo não enviado"}), 400
    file = request.files["file"]
    if not file.filename.endswith(".csv"):
        return jsonify({"error": "Formato inválido. Use .csv"}), 400

    stream = io.StringIO(file.stream.read().decode("utf-8"), newline=None)
    reader = csv.DictReader(stream)

    if not reader.fieldnames:
        return jsonify({"error": "CSV vazio ou sem cabeçalho"}), 400

    # Normalize headers
    headers = [h.strip().lower() for h in reader.fieldnames]
    # Required: at least one of produto_sku or produto_nome, and quantidade
    has_sku  = "produto_sku"  in headers or "sku"      in headers
    has_name = "produto_nome" in headers or "nome"     in headers or "produto" in headers
    has_qty  = "quantidade"   in headers or "qtd"      in headers or "qty"    in headers
    if not (has_sku or has_name) or not has_qty:
        return jsonify({"error": "Colunas obrigatórias: produto_sku e/ou produto_nome, quantidade"}), 400

    # Remap to canonical names
    def col(row, *keys):
        for k in keys:
            if k in row and row[k] is not None and str(row[k]).strip():
                return str(row[k]).strip()
        return ""

    results = {"created": 0, "updated": 0, "errors": []}

    with db_transaction():
        for i, row in enumerate(reader):
            row = {k.strip().lower(): v for k, v in row.items()}
            try:
                sku      = col(row, "produto_sku", "sku")
                name     = col(row, "produto_nome", "nome", "produto")
                qty_str  = col(row, "quantidade", "qtd", "qty")
                obs      = col(row, "observacao", "obs", "observation")

                if not sku and not name:
                    results["errors"].append(f"Linha {i+2}: produto_sku ou produto_nome é obrigatório")
                    continue
                try:
                    qty = float(qty_str.replace(",", ".")) if qty_str else 0
                except ValueError:
                    results["errors"].append(f"Linha {i+2}: quantidade inválida '{qty_str}'")
                    continue
                if qty <= 0:
                    results["errors"].append(f"Linha {i+2}: quantidade deve ser maior que zero")
                    continue

                # Find product: SKU first, then name
                product = None
                if sku:
                    product = query_db("SELECT id, name FROM products WHERE sku=? AND active=1 LIMIT 1", [sku], one=True)
                if not product and name:
                    product = query_db("SELECT id, name FROM products WHERE lower(name)=lower(?) AND active=1 LIMIT 1", [name], one=True)
                if not product and name:
                    product = query_db("SELECT id, name FROM products WHERE name LIKE ? AND active=1 LIMIT 1", [f"%{name}%"], one=True)
                if not product:
                    label = sku or name
                    results["errors"].append(f"Linha {i+2}: produto não encontrado '{label}'")
                    continue

                pid = product["id"]
                # Upsert need
                existing = query_db(
                    "SELECT id, quantity_needed FROM project_needs WHERE project_id=? AND product_id=?",
                    [project_id, pid], one=True
                )
                if existing:
                    execute_db(
                        "UPDATE project_needs SET quantity_needed=?, observation=COALESCE(NULLIF(?,''),observation), updated_at=datetime('now') WHERE id=?",
                        [qty, obs or None, existing["id"]], commit=False
                    )
                    log_action("update", "project_need", entity_id=existing["id"],
                               details={"project_id": project_id, "product_id": pid,
                                        "quantity_needed": qty, "source": "csv_import"})
                    results["updated"] += 1
                else:
                    nid = str(uuid.uuid4())
                    execute_db(
                        "INSERT INTO project_needs (id, project_id, product_id, quantity_needed, observation) VALUES (?,?,?,?,?)",
                        [nid, project_id, pid, qty, obs or None], commit=False
                    )
                    log_action("create", "project_need", entity_id=nid,
                               details={"project_id": project_id, "product_id": pid,
                                        "quantity_needed": qty, "source": "csv_import"})
                    results["created"] += 1

            except Exception as e:
                results["errors"].append(f"Linha {i+2}: {str(e)}")

    return jsonify(results)


@projects_bp.route("/<project_id>/match", methods=["POST"])
@require_role("admin", "manager")
def run_match(project_id):
    project = query_db("SELECT * FROM projects WHERE id=?", [project_id], one=True)
    if not project:
        return jsonify({"error": "Projeto não encontrado"}), 404
    needs = query_db(
        "SELECT * FROM project_needs WHERE project_id=? AND status IN ('pending','partial')",
        [project_id]
    )
    results = []
    with db_transaction():
        for need in needs:
            need = dict(need)
            product = row_to_dict(query_db("SELECT * FROM products WHERE id=? AND active=1", [need["product_id"]], one=True))
            if not product:
                continue
            available = float(product["stock"]) - float(product["reserved_stock"])
            missing = max(0.0, float(need["quantity_needed"]) - float(need["quantity_reserved"]))
            can_reserve = min(missing, max(0.0, available))
            if can_reserve > 0:
                execute_db(
                    "UPDATE products SET reserved_stock=reserved_stock+?, updated_at=datetime('now') WHERE id=?",
                    [can_reserve, product["id"]], commit=False
                )
                new_reserved = float(need["quantity_reserved"]) + can_reserve
                execute_db(
                    "UPDATE project_needs SET quantity_reserved=?, updated_at=datetime('now') WHERE id=?",
                    [new_reserved, need["id"]], commit=False
                )
                new_missing = max(0.0, float(need["quantity_needed"]) - new_reserved)
                status = "fulfilled" if new_missing == 0 else "partial"
                execute_db(
                    "UPDATE project_needs SET status=? WHERE id=?",
                    [status, need["id"]], commit=False
                )
                results.append({
                    "need_id": need["id"],
                    "product_id": product["id"],
                    "product_name": product["name"],
                    "needed": float(need["quantity_needed"]),
                    "reserved": new_reserved,
                    "missing": new_missing,
                    "status": status,
                    "matched": can_reserve
                })
            else:
                results.append({
                    "need_id": need["id"],
                    "product_id": product["id"],
                    "product_name": product["name"],
                    "needed": float(need["quantity_needed"]),
                    "reserved": float(need["quantity_reserved"]),
                    "missing": missing,
                    "status": need["status"],
                    "matched": 0
                })
    matched_count = sum(1 for r in results if r["matched"] > 0)
    fulfilled_count = sum(1 for r in results if r["status"] == "fulfilled")
    log_action("run_match", "project", entity_id=project_id,
               details={"total_needs": len(results), "matched": matched_count,
                        "fulfilled": fulfilled_count})
    return jsonify({
        "results": results,
        "summary": {
            "total_needs": len(results),
            "matched": matched_count,
            "fulfilled": fulfilled_count,
            "pending": len(results) - fulfilled_count
        }
    })
