from flask import Blueprint, request, jsonify
from app.core.jwt_utils import require_role, get_current_user
from app.core.database import query_db, execute_db, row_to_dict, rows_to_dicts
from app.core.audit import log_action
import uuid
import csv
import io
from app.core.database import query_db, execute_db, row_to_dict, rows_to_dicts, db_transaction

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
    paginated = request.args.get("page") is not None

    where = " WHERE 1=1"
    args = []
    if active_only:
        where += " AND p.active=1"
    if search:
        where += " AND (p.name LIKE ? OR p.sku LIKE ? OR p.barcode LIKE ?)"
        args += [f"%{search}%", f"%{search}%", f"%{search}%"]
    if category_id:
        where += " AND p.category_id=?"
        args.append(category_id)

    q = f"""SELECT p.*, c.name as category_name FROM products p
            LEFT JOIN categories c ON p.category_id = c.id {where} ORDER BY p.name"""

    if paginated:
        try:
            page = max(int(request.args.get("page", 1)), 1)
            per_page = min(int(request.args.get("per_page", 50)), 200)
        except (TypeError, ValueError):
            page, per_page = 1, 50

        count_q = f"SELECT COUNT(*) as total FROM products p {where}"
        total = query_db(count_q, args, one=True)["total"]

        q += f" LIMIT {per_page} OFFSET {(page - 1) * per_page}"
        rows = query_db(q, args)
        result = []
        for row in rows:
            d = product_row(row)
            d["category"] = {"id": d["category_id"], "name": d["category_name"]} if d.get("category_id") and d.get("category_name") else None
            result.append(d)
        return jsonify({
            "data": result, "total": total,
            "page": page, "per_page": per_page,
            "pages": (total + per_page - 1) // per_page
        })

    # Legacy mode: return flat array
    rows = query_db(q, args)
    result = []
    for row in rows:
        d = product_row(row)
        d["category"] = {"id": d["category_id"], "name": d["category_name"]} if d.get("category_id") and d.get("category_name") else None
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
    rows = rows_to_dicts(query_db("SELECT * FROM categories WHERE active=1 ORDER BY name"))
    return jsonify(rows)

@products_bp.route("/categories/", methods=["POST"])
@require_role("admin", "manager")
def create_category():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Nome é obrigatório"}), 400
    exists = query_db("SELECT * FROM categories WHERE lower(name)=lower(?) AND active=1 LIMIT 1", [name], one=True)
    if exists:
        return jsonify({"error": "Categoria já existe"}), 400
    cid = str(uuid.uuid4())
    execute_db("INSERT INTO categories (id, name, description, active) VALUES (?,?,?,1)",
               [cid, name, (data.get("description") or "").strip() or None])
    cat = row_to_dict(query_db("SELECT * FROM categories WHERE id=?", [cid], one=True))
    log_action("create", "category", entity_id=cid, details={"name": name})
    return jsonify(cat), 201

@products_bp.route("/categories/<category_id>", methods=["PUT"])
@require_role("admin", "manager")
def update_category(category_id):
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Nome é obrigatório"}), 400
    # Check duplicate name (excluding current)
    exists = query_db(
        "SELECT * FROM categories WHERE lower(name)=lower(?) AND id!=? AND active=1 LIMIT 1",
        [name, category_id], one=True
    )
    if exists:
        return jsonify({"error": "Já existe uma categoria com esse nome"}), 400
    execute_db(
        "UPDATE categories SET name=?, description=? WHERE id=?",
        [name, (data.get("description") or "").strip() or None, category_id]
    )
    cat = row_to_dict(query_db("SELECT * FROM categories WHERE id=?", [category_id], one=True))
    if not cat:
        return jsonify({"error": "Categoria não encontrada"}), 404
    log_action("update", "category", entity_id=category_id, details={"name": name})
    return jsonify(cat)

@products_bp.route("/categories/<category_id>", methods=["DELETE"])
@require_role("admin", "manager")
def delete_category(category_id):
    cat = query_db("SELECT * FROM categories WHERE id=? AND active=1", [category_id], one=True)
    if not cat:
        return jsonify({"error": "Categoria não encontrada"}), 404
    # Check if any active product uses this category
    in_use = query_db(
        "SELECT COUNT(*) as c FROM products WHERE category_id=? AND active=1",
        [category_id], one=True
    )
    if in_use and in_use["c"] > 0:
        return jsonify({"error": f"Categoria em uso por {in_use['c']} produto(s). Reassine os produtos antes de excluir."}), 409
    execute_db("UPDATE categories SET active=0 WHERE id=?", [category_id])
    log_action("delete", "category", entity_id=category_id,
               details={"name": dict(cat).get("name")})
    return jsonify({"message": "Categoria removida"})

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
        error_str = str(e)
        if "UNIQUE" in error_str.upper():
            return jsonify({"error": "SKU já cadastrado"}), 409
        return jsonify({"error": error_str}), 400
    row = query_db("SELECT * FROM products WHERE id=?", [pid], one=True)
    log_action("create", "product", entity_id=pid,
               details={"name": name, "sku": data.get("sku"), "unit": data.get("unit", "un")})
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
    sets.append("updated_at=datetime('now')")
    vals.append(product_id)
    execute_db(f"UPDATE products SET {','.join(sets)} WHERE id=?", vals)
    row = query_db("SELECT * FROM products WHERE id=?", [product_id], one=True)
    log_action("update", "product", entity_id=product_id,
               details={k: data[k] for k in data if k != "password"})
    return jsonify(product_row(row))

@products_bp.route("/<product_id>", methods=["DELETE"])
@require_role("admin")
def delete_product(product_id):
    row = query_db("SELECT name FROM products WHERE id=?", [product_id], one=True)
    execute_db("UPDATE products SET active=0, updated_at=datetime('now') WHERE id=?", [product_id])
    log_action("delete", "product", entity_id=product_id,
               details={"name": dict(row).get("name") if row else None})
    return jsonify({"message": "Inativado"})

@products_bp.route("/<product_id>/history", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def product_history(product_id):
    """Full timeline of a product: movements, invoices, quotations, project allocations."""
    product = query_db("SELECT * FROM products WHERE id=?", [product_id], one=True)
    if not product:
        return jsonify({"error": "Produto não encontrado"}), 404

    timeline = []

    # Movements
    movements = query_db("""
        SELECT m.id, m.type, m.quantity, m.unit_cost, m.observation,
               m.created_at, m.invoice_number,
               u.name as user_name, pr.name as project_name, s.name as supplier_name
        FROM movements m
        LEFT JOIN users u ON m.user_id = u.id
        LEFT JOIN projects pr ON m.project_id = pr.id
        LEFT JOIN suppliers s ON m.supplier_id = s.id
        WHERE m.product_id = ?
        ORDER BY m.created_at DESC
    """, [product_id])
    for row in movements:
        d = dict(row)
        type_labels = {"entry": "Entrada", "exit": "Saída", "adjustment": "Ajuste", "reservation": "Reserva"}
        timeline.append({
            "category": "movement",
            "type": d["type"],
            "title": type_labels.get(d["type"], d["type"]),
            "description": f"Qtd: {d['quantity']} | {d['user_name'] or 'Sistema'}",
            "details": {
                "quantity": d["quantity"], "unit_cost": d["unit_cost"],
                "user": d["user_name"], "project": d["project_name"],
                "supplier": d["supplier_name"], "invoice": d["invoice_number"],
                "observation": d["observation"]
            },
            "date": d["created_at"],
            "id": d["id"]
        })

    # Invoice items linked to this product
    invoice_items = query_db("""
        SELECT ii.quantity, ii.unit_price, ii.total_price, ii.description as item_desc,
               i.invoice_number, i.supplier_name, i.issue_date, i.status, i.id as invoice_id
        FROM invoice_items ii
        JOIN invoices i ON ii.invoice_id = i.id
        WHERE ii.product_id = ?
        ORDER BY i.issue_date DESC
    """, [product_id])
    for row in invoice_items:
        d = dict(row)
        timeline.append({
            "category": "invoice",
            "type": d["status"],
            "title": f"NF {d['invoice_number']}",
            "description": f"{d['supplier_name'] or '—'} | Qtd: {d['quantity']} x R$ {d['unit_price']:.2f}",
            "details": {
                "invoice_number": d["invoice_number"], "supplier": d["supplier_name"],
                "quantity": d["quantity"], "unit_price": d["unit_price"],
                "total_price": d["total_price"]
            },
            "date": d["issue_date"],
            "id": d["invoice_id"]
        })

    # Quotations
    quotations = query_db("""
        SELECT q.id, q.quantity, q.status, q.created_at, q.notes,
               s.name as approved_supplier
        FROM quotations q
        LEFT JOIN suppliers s ON q.approved_supplier_id = s.id
        WHERE q.product_id = ?
        ORDER BY q.created_at DESC
    """, [product_id])
    for row in quotations:
        d = dict(row)
        status_labels = {"open": "Aberta", "received": "Recebida", "approved": "Aprovada", "closed": "Fechada"}
        timeline.append({
            "category": "quotation",
            "type": d["status"],
            "title": f"Cotação — {status_labels.get(d['status'], d['status'])}",
            "description": f"Qtd: {d['quantity']}" + (f" | Fornecedor: {d['approved_supplier']}" if d["approved_supplier"] else ""),
            "details": {
                "quantity": d["quantity"], "status": d["status"],
                "supplier": d["approved_supplier"], "notes": d["notes"]
            },
            "date": d["created_at"],
            "id": d["id"]
        })

    # Project allocations
    project_needs = query_db("""
        SELECT pn.quantity_needed, pn.quantity_reserved, pn.status, pn.created_at,
               p.name as project_name, p.id as project_id
        FROM project_needs pn
        JOIN projects p ON pn.project_id = p.id
        WHERE pn.product_id = ?
        ORDER BY pn.created_at DESC
    """, [product_id])
    for row in project_needs:
        d = dict(row)
        timeline.append({
            "category": "project",
            "type": d["status"],
            "title": f"Projeto: {d['project_name']}",
            "description": f"Necessário: {d['quantity_needed']} | Reservado: {d['quantity_reserved']}",
            "details": {
                "project": d["project_name"], "needed": d["quantity_needed"],
                "reserved": d["quantity_reserved"], "status": d["status"]
            },
            "date": d["created_at"],
            "id": d["project_id"]
        })

    # Sort by date descending
    timeline.sort(key=lambda x: x.get("date") or "", reverse=True)

    return jsonify({
        "product": product_row(dict(product)),
        "timeline": timeline,
        "counts": {
            "movements": len([t for t in timeline if t["category"] == "movement"]),
            "invoices": len([t for t in timeline if t["category"] == "invoice"]),
            "quotations": len([t for t in timeline if t["category"] == "quotation"]),
            "projects": len([t for t in timeline if t["category"] == "project"]),
        }
    })


@products_bp.route("/import/csv", methods=["POST"])
@require_role("admin")
def import_csv():
    if "file" not in request.files:
        return jsonify({"error": "Arquivo não enviado"}), 400
    
    file = request.files["file"]
    if not file.filename.endswith(".csv"):
        return jsonify({"error": "Formato inválido. Use .csv"}), 400

    stream = io.StringIO(file.stream.read().decode("utf-8"), newline=None)
    reader = csv.DictReader(stream, delimiter=";")
    
    # Required columns check
    required_cols = {"nome", "sku", "categoria", "estoque", "preco_custo", "preco_venda", "unidade"}
    if not required_cols.issubset(set(reader.fieldnames or [])):
        return jsonify({"error": f"Colunas ausentes. O CSV deve conter: {', '.join(required_cols)}"}), 400

    results = {"created": 0, "updated": 0, "errors": []}
    
    with db_transaction():
        for i, row in enumerate(reader):
            try:
                name = row["nome"].strip()
                sku = row["sku"].strip()
                category_name = row["categoria"].strip()
                stock = float(row.get("estoque", 0) or 0)
                cost = float(row.get("preco_custo", 0) or 0)
                price = float(row.get("preco_venda", 0) or 0)
                unit = row.get("unidade", "un").strip()
                barcode = row.get("codigo_barras", "").strip()
                min_stock = float(row.get("estoque_minimo", 0) or 0)
                desc = row.get("descricao", "").strip()
                supplier_name = row.get("fornecedor", "").strip()

                if not name:
                    results["errors"].append(f"Linha {i+2}: Nome é obrigatório")
                    continue

                # Handle Category
                category_id = None
                if category_name:
                    cat = query_db("SELECT id FROM categories WHERE lower(name)=lower(?) AND active=1 LIMIT 1", [category_name], one=True)
                    if cat:
                        category_id = cat["id"]
                    else:
                        category_id = str(uuid.uuid4())
                        execute_db("INSERT INTO categories (id, name, active) VALUES (?,?,1)", [category_id, category_name], commit=False)

                # Handle Product
                existing = None
                if sku:
                    existing = query_db("SELECT id FROM products WHERE sku=? LIMIT 1", [sku], one=True)
                
                if not existing:
                    pid = str(uuid.uuid4())
                    execute_db("""INSERT INTO products (id, name, description, sku, barcode, category_id,
                               cost_price, sale_price, stock, min_stock, unit) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                               [pid, name, desc, sku, barcode, category_id, cost, price, stock, min_stock, unit], commit=False)
                    results["created"] += 1
                    log_action("create", "product", entity_id=pid, details={"name": name, "sku": sku, "source": "csv_import"})
                else:
                    pid = existing["id"]
                    execute_db("""UPDATE products SET name=?, description=?, barcode=?, category_id=?,
                               cost_price=?, sale_price=?, stock=?, min_stock=?, unit=?, active=1, updated_at=datetime('now')
                               WHERE id=?""",
                               [name, desc, barcode, category_id, cost, price, stock, min_stock, unit, pid], commit=False)
                    results["updated"] += 1
                    log_action("update", "product", entity_id=pid, details={"name": name, "sku": sku, "source": "csv_import"})

                # Handle Supplier association
                if supplier_name:
                    sup = query_db("SELECT id FROM suppliers WHERE lower(name)=lower(?) AND active=1 LIMIT 1", [supplier_name], one=True)
                    if sup:
                        sid = sup["id"]
                        # Check if link exists
                        link = query_db("SELECT id FROM product_suppliers WHERE product_id=? AND supplier_id=? LIMIT 1", [pid, sid], one=True)
                        if not link:
                            execute_db("INSERT INTO product_suppliers (id, product_id, supplier_id, avg_price) VALUES (?,?,?,?)",
                                       [str(uuid.uuid4()), pid, sid, cost], commit=False)

            except Exception as e:
                results["errors"].append(f"Linha {i+2}: {str(e)}")

    return jsonify(results)
