from flask import Blueprint, request, jsonify
from app.core.jwt_utils import require_role, get_current_user
from app.core.database import query_db, execute_db, row_to_dict, rows_to_dicts
from app.core.audit import log_action
import uuid
import re

suppliers_bp = Blueprint("suppliers", __name__)


def _clean_cnpj(cnpj: str) -> str:
    """Strip non-digit characters from CNPJ string."""
    return re.sub(r'\D', '', cnpj or "")


def _validate_cnpj(cnpj: str) -> bool:
    """
    Validates a Brazilian CNPJ using the official two-check-digit algorithm.
    Accepts formatted (XX.XXX.XXX/XXXX-XX) or raw (14 digits) strings.
    """
    cnpj = _clean_cnpj(cnpj)
    if len(cnpj) != 14:
        return False
    if len(set(cnpj)) == 1:
        return False

    def _calc(digits, weights):
        s = sum(int(d) * w for d, w in zip(digits, weights))
        r = s % 11
        return 0 if r < 2 else 11 - r

    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    if _calc(cnpj[:12], w1) != int(cnpj[12]):
        return False
    w2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    return _calc(cnpj[:13], w2) == int(cnpj[13])


# ─────────────────────────────────────────────────────────────
# Suppliers CRUD
# ─────────────────────────────────────────────────────────────

@suppliers_bp.route("/", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def list_suppliers():
    include_inactive = request.args.get("include_inactive", "0") == "1"
    current = get_current_user()
    actor_role = current.get("role", "")
    # Only admin/manager can see inactive suppliers
    if include_inactive and actor_role not in ("admin", "manager"):
        include_inactive = False
    where = "" if include_inactive else " WHERE active=1"
    return jsonify(rows_to_dicts(query_db(f"SELECT * FROM suppliers{where} ORDER BY name")))


@suppliers_bp.route("/", methods=["POST"])
@require_role("admin", "manager")
def create_supplier():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Nome é obrigatório"}), 400
    cnpj = data.get("cnpj") or ""
    if cnpj:
        raw_cnpj = _clean_cnpj(cnpj)
        if len(raw_cnpj) > 0 and not _validate_cnpj(cnpj):
            return jsonify({"error": "CNPJ inválido"}), 400
        # Check for duplicate CNPJ
        existing = query_db(
            "SELECT id FROM suppliers WHERE REPLACE(REPLACE(REPLACE(REPLACE(cnpj,'.','' ),'/',''),'-',''),' ','')=? LIMIT 1",
            [raw_cnpj], one=True
        )
        if existing:
            return jsonify({"error": "Já existe um fornecedor cadastrado com este CNPJ"}), 409
    sid = str(uuid.uuid4())
    try:
        execute_db(
            "INSERT INTO suppliers (id, name, cnpj, email, phone, address, contact_name, avg_lead_time) VALUES (?,?,?,?,?,?,?,?)",
            [sid, name, cnpj or None, data.get("email"), data.get("phone"),
             data.get("address"), data.get("contact_name"), data.get("avg_lead_time", 7)]
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    supplier = row_to_dict(query_db("SELECT * FROM suppliers WHERE id=?", [sid], one=True))
    log_action("create", "supplier", entity_id=sid,
               details={"name": name, "cnpj": cnpj, "email": data.get("email")})
    return jsonify(supplier), 201


@suppliers_bp.route("/<supplier_id>", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def get_supplier(supplier_id):
    row = query_db("SELECT * FROM suppliers WHERE id=?", [supplier_id], one=True)
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row_to_dict(row))


@suppliers_bp.route("/<supplier_id>", methods=["PUT"])
@require_role("admin", "manager", "buyer")
def update_supplier(supplier_id):
    current = get_current_user()
    actor_role = current.get("role", "")
    data = request.get_json() or {}
    if "name" in data and not str(data.get("name") or "").strip():
        return jsonify({"error": "Nome é obrigatório"}), 400
    # Validate CNPJ if provided
    if "cnpj" in data and data["cnpj"]:
        if not _validate_cnpj(data["cnpj"]):
            return jsonify({"error": "CNPJ inválido"}), 400
        raw_cnpj = _clean_cnpj(data["cnpj"])
        existing = query_db(
            "SELECT id FROM suppliers WHERE REPLACE(REPLACE(REPLACE(REPLACE(cnpj,'.','' ),'/',''),'-',''),' ','')=? AND id!=? LIMIT 1",
            [raw_cnpj, supplier_id], one=True
        )
        if existing:
            return jsonify({"error": "Já existe outro fornecedor com este CNPJ"}), 409
    # Only admin/manager may toggle the active flag
    if "active" in data and actor_role not in ("admin", "manager"):
        return jsonify({"error": "Sem permissão para ativar/desativar fornecedores"}), 403
    sets, vals = [], []
    for f in ["name", "cnpj", "email", "phone", "address", "contact_name", "avg_lead_time", "rating", "active"]:
        if f in data:
            sets.append(f"{f}=?")
            vals.append(data[f])
    if not sets:
        return jsonify({"error": "No data"}), 400
    # note: suppliers table has no updated_at column
    vals.append(supplier_id)
    execute_db(f"UPDATE suppliers SET {','.join(sets)} WHERE id=?", vals)
    supplier = row_to_dict(query_db("SELECT * FROM suppliers WHERE id=?", [supplier_id], one=True))
    log_action("update", "supplier", entity_id=supplier_id,
               details={k: data[k] for k in data if k in ["name", "cnpj", "email", "phone", "active", "rating"]})
    return jsonify(supplier)


@suppliers_bp.route("/<supplier_id>/deactivate", methods=["POST"])
@require_role("admin", "manager")
def deactivate_supplier(supplier_id):
    row = query_db("SELECT id, name, active FROM suppliers WHERE id=?", [supplier_id], one=True)
    if not row:
        return jsonify({"error": "Fornecedor não encontrado"}), 404
    execute_db("UPDATE suppliers SET active=0 WHERE id=?", [supplier_id])
    log_action("deactivate", "supplier", entity_id=supplier_id,
               details={"name": row["name"]})
    return jsonify({"id": supplier_id, "active": False})


@suppliers_bp.route("/<supplier_id>/activate", methods=["POST"])
@require_role("admin", "manager")
def activate_supplier(supplier_id):
    row = query_db("SELECT id, name, active FROM suppliers WHERE id=?", [supplier_id], one=True)
    if not row:
        return jsonify({"error": "Fornecedor não encontrado"}), 404
    execute_db("UPDATE suppliers SET active=1 WHERE id=?", [supplier_id])
    log_action("activate", "supplier", entity_id=supplier_id,
               details={"name": row["name"]})
    return jsonify({"id": supplier_id, "active": True})


@suppliers_bp.route("/<supplier_id>/summary", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def supplier_summary(supplier_id):
    """
    Returns a full supplier profile with linked products, recent invoices,
    recent movements, and quotation history.
    """
    supplier = row_to_dict(query_db("SELECT * FROM suppliers WHERE id=?", [supplier_id], one=True))
    if not supplier:
        return jsonify({"error": "Fornecedor não encontrado"}), 404

    # Linked products
    linked_products = rows_to_dicts(query_db(
        """SELECT ps.*, p.name as product_name, p.sku, p.unit, p.stock, p.min_stock
           FROM product_suppliers ps
           LEFT JOIN products p ON ps.product_id = p.id
           WHERE ps.supplier_id=? ORDER BY ps.priority""",
        [supplier_id]
    ))

    # Recent invoices (last 20)
    invoices = rows_to_dicts(query_db(
        """SELECT id, invoice_number, issue_date, total_value, status,
                  created_at, source_file_name,
                  (SELECT COUNT(*) FROM invoice_items ii WHERE ii.invoice_id=invoices.id) as items_count
           FROM invoices WHERE supplier_id=?
           ORDER BY created_at DESC LIMIT 20""",
        [supplier_id]
    ))

    # Recent movements (last 30)
    movements = rows_to_dicts(query_db(
        """SELECT m.id, m.type, m.quantity, m.unit_cost, m.invoice_number, m.created_at,
                  p.name as product_name, p.unit as product_unit
           FROM movements m
           LEFT JOIN products p ON m.product_id = p.id
           WHERE m.supplier_id=?
           ORDER BY m.created_at DESC LIMIT 30""",
        [supplier_id]
    ))

    # Quotation history (open/received/approved)
    quotations = rows_to_dicts(query_db(
        """SELECT q.id, q.status, q.quantity, q.created_at,
                  p.name as product_name,
                  qi.unit_price, qi.lead_time, qi.status as item_status
           FROM quotation_items qi
           JOIN quotations q ON qi.quotation_id = q.id
           LEFT JOIN products p ON q.product_id = p.id
           WHERE qi.supplier_id=?
           ORDER BY q.created_at DESC LIMIT 20""",
        [supplier_id]
    ))

    # Stats
    stats = {
        "total_invoices": query_db("SELECT COUNT(*) as c FROM invoices WHERE supplier_id=?", [supplier_id], one=True)["c"],
        "total_invoices_value": (row_to_dict(query_db("SELECT COALESCE(SUM(total_value),0) as s FROM invoices WHERE supplier_id=? AND status='processed'", [supplier_id], one=True)) or {}).get("s", 0),
        "total_movements": query_db("SELECT COUNT(*) as c FROM movements WHERE supplier_id=?", [supplier_id], one=True)["c"],
        "open_quotations": query_db("SELECT COUNT(*) as c FROM quotation_items qi JOIN quotations q ON qi.quotation_id=q.id WHERE qi.supplier_id=? AND q.status IN ('open','received')", [supplier_id], one=True)["c"],
    }

    return jsonify({
        "supplier": supplier,
        "stats": stats,
        "linked_products": linked_products,
        "invoices": invoices,
        "movements": movements,
        "quotations": quotations,
    })


# ─────────────────────────────────────────────────────────────
# Product-Supplier links
# ─────────────────────────────────────────────────────────────

@suppliers_bp.route("/product-link", methods=["POST"])
@require_role("admin", "manager", "buyer")
def link_product():
    data = request.get_json() or {}
    if not data.get("product_id") or not data.get("supplier_id"):
        return jsonify({"error": "Produto e fornecedor são obrigatórios"}), 400
    # Prevent duplicate link
    existing = query_db(
        "SELECT id FROM product_suppliers WHERE product_id=? AND supplier_id=?",
        [data["product_id"], data["supplier_id"]], one=True
    )
    if existing:
        return jsonify({"error": "Este produto já está vinculado a este fornecedor"}), 409
    lid = str(uuid.uuid4())
    execute_db(
        "INSERT INTO product_suppliers (id, product_id, supplier_id, avg_price, lead_time, priority, notes) VALUES (?,?,?,?,?,?,?)",
        [lid, data["product_id"], data["supplier_id"], data.get("avg_price", 0),
         data.get("lead_time", 7), data.get("priority", 1), data.get("notes")]
    )
    log_action("create", "product_supplier_link", entity_id=lid,
               details={"product_id": data["product_id"], "supplier_id": data["supplier_id"]})
    return jsonify(row_to_dict(query_db("SELECT * FROM product_suppliers WHERE id=?", [lid], one=True))), 201


@suppliers_bp.route("/product-link/<link_id>", methods=["PUT"])
@require_role("admin", "manager", "buyer")
def update_product_link(link_id):
    data = request.get_json() or {}
    sets, vals = [], []
    for f in ["avg_price", "lead_time", "priority", "notes"]:
        if f in data:
            sets.append(f"{f}=?")
            vals.append(data[f])
    if not sets:
        return jsonify({"error": "No data"}), 400
    vals.append(link_id)
    execute_db(f"UPDATE product_suppliers SET {','.join(sets)} WHERE id=?", vals)
    link = row_to_dict(query_db("SELECT * FROM product_suppliers WHERE id=?", [link_id], one=True))
    if not link:
        return jsonify({"error": "Vínculo não encontrado"}), 404
    log_action("update", "product_supplier_link", entity_id=link_id, details=data)
    return jsonify(link)


@suppliers_bp.route("/product-link/<link_id>", methods=["DELETE"])
@require_role("admin", "manager", "buyer")
def delete_product_link(link_id):
    link = row_to_dict(query_db("SELECT * FROM product_suppliers WHERE id=?", [link_id], one=True))
    if not link:
        return jsonify({"error": "Vínculo não encontrado"}), 404
    execute_db("DELETE FROM product_suppliers WHERE id=?", [link_id])
    log_action("delete", "product_supplier_link", entity_id=link_id,
               details={"product_id": link.get("product_id"), "supplier_id": link.get("supplier_id")})
    return jsonify({"deleted": True})


@suppliers_bp.route("/product/<product_id>", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def product_suppliers(product_id):
    rows = query_db(
        """SELECT ps.*, s.name as supplier_name, s.cnpj as supplier_cnpj,
                  s.email as supplier_email, s.rating as supplier_rating,
                  s.active as supplier_active
           FROM product_suppliers ps
           LEFT JOIN suppliers s ON ps.supplier_id = s.id
           WHERE ps.product_id=? ORDER BY ps.priority""",
        [product_id]
    )
    return jsonify(rows_to_dicts(rows))


# ─────────────────────────────────────────────────────────────
# Quotations
# ─────────────────────────────────────────────────────────────

@suppliers_bp.route("/quotations/", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def list_quotations():
    status_filter = request.args.get("status")  # open, received, approved, cancelled
    q = """SELECT q.*, p.name as product_name FROM quotations q
           LEFT JOIN products p ON q.product_id = p.id"""
    args = []
    if status_filter:
        q += " WHERE q.status=?"
        args.append(status_filter)
    q += " ORDER BY q.created_at DESC"
    rows = query_db(q, args)
    result = []
    for row in rows:
        d = dict(row)
        items = rows_to_dicts(query_db(
            """SELECT qi.*, s.name as supplier_name, s.cnpj as supplier_cnpj
               FROM quotation_items qi
               LEFT JOIN suppliers s ON qi.supplier_id = s.id
               WHERE qi.quotation_id=?""",
            [d["id"]]
        ))
        d["items"] = items
        # Attach approved supplier name if applicable
        if d.get("approved_supplier_id"):
            sup = query_db("SELECT name FROM suppliers WHERE id=?", [d["approved_supplier_id"]], one=True)
            d["approved_supplier_name"] = sup["name"] if sup else None
        result.append(d)
    return jsonify(result)


@suppliers_bp.route("/quotations/", methods=["POST"])
@require_role("admin", "manager", "buyer")
def create_quotation():
    data = request.get_json() or {}
    product_id = data.get("product_id")
    try:
        qty = float(data.get("quantity", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Quantidade inválida"}), 400
    if not product_id:
        return jsonify({"error": "Produto é obrigatório"}), 400
    if qty <= 0:
        return jsonify({"error": "Quantidade inválida"}), 400
    # Validate product exists
    product = query_db("SELECT id, name FROM products WHERE id=? AND active=1", [product_id], one=True)
    if not product:
        return jsonify({"error": "Produto não encontrado ou inativo"}), 404
    qid = str(uuid.uuid4())
    execute_db(
        "INSERT INTO quotations (id, project_need_id, product_id, quantity, notes) VALUES (?,?,?,?,?)",
        [qid, data.get("project_need_id"), product_id, qty, data.get("notes")]
    )
    # Auto-add linked active suppliers
    linked = query_db(
        """SELECT ps.* FROM product_suppliers ps
           JOIN suppliers s ON ps.supplier_id = s.id
           WHERE ps.product_id=? AND s.active=1""",
        [product_id]
    )
    for ps in linked:
        execute_db(
            "INSERT INTO quotation_items (id, quotation_id, supplier_id, unit_price, lead_time) VALUES (?,?,?,?,?)",
            [str(uuid.uuid4()), qid, ps["supplier_id"], ps["avg_price"], ps["lead_time"]]
        )
    quotation = row_to_dict(query_db("SELECT * FROM quotations WHERE id=?", [qid], one=True))
    log_action("create_quotation", "quotation", entity_id=qid,
               details={"product_id": product_id, "product_name": product["name"], "quantity": qty})
    return jsonify(quotation), 201


@suppliers_bp.route("/quotations/<quotation_id>/approve", methods=["POST"])
@require_role("admin", "manager")
def approve_quotation(quotation_id):
    data = request.get_json() or {}
    if not data.get("supplier_id"):
        return jsonify({"error": "Fornecedor é obrigatório"}), 400
    quotation = row_to_dict(query_db("SELECT * FROM quotations WHERE id=?", [quotation_id], one=True))
    if not quotation:
        return jsonify({"error": "Cotação não encontrada"}), 404
    if quotation.get("status") not in ("open", "received"):
        return jsonify({"error": "Apenas cotações abertas ou recebidas podem ser aprovadas"}), 400
    # Check that supplier is linked to this quotation
    item = query_db(
        "SELECT * FROM quotation_items WHERE quotation_id=? AND supplier_id=?",
        [quotation_id, data["supplier_id"]], one=True
    )
    if not item:
        return jsonify({"error": "Fornecedor não está vinculado a esta cotação"}), 400
    execute_db(
        "UPDATE quotations SET status='approved', approved_supplier_id=? WHERE id=?",
        [data["supplier_id"], quotation_id]
    )
    execute_db(
        "UPDATE quotation_items SET status='approved' WHERE quotation_id=? AND supplier_id=?",
        [quotation_id, data["supplier_id"]]
    )
    execute_db(
        "UPDATE quotation_items SET status='rejected' WHERE quotation_id=? AND supplier_id!=?",
        [quotation_id, data["supplier_id"]]
    )
    quotation = row_to_dict(query_db("SELECT * FROM quotations WHERE id=?", [quotation_id], one=True))
    log_action("approve_quotation", "quotation", entity_id=quotation_id,
               details={"approved_supplier_id": data["supplier_id"]})
    return jsonify(quotation)


@suppliers_bp.route("/quotations/<quotation_id>/cancel", methods=["POST"])
@require_role("admin", "manager")
def cancel_quotation(quotation_id):
    quotation = row_to_dict(query_db("SELECT * FROM quotations WHERE id=?", [quotation_id], one=True))
    if not quotation:
        return jsonify({"error": "Cotação não encontrada"}), 404
    if quotation.get("status") == "approved":
        return jsonify({"error": "Cotações aprovadas não podem ser canceladas"}), 400
    data = request.get_json() or {}
    reason = (data.get("reason") or "").strip()
    execute_db("UPDATE quotations SET status='cancelled' WHERE id=?", [quotation_id])
    log_action("cancel_quotation", "quotation", entity_id=quotation_id,
               details={"reason": reason, "previous_status": quotation.get("status")})
    return jsonify({"id": quotation_id, "status": "cancelled"})


@suppliers_bp.route("/quotations/<quotation_id>/add-supplier", methods=["POST"])
@require_role("admin", "manager", "buyer")
def add_supplier_to_quotation(quotation_id):
    """Manually add a supplier to an open quotation."""
    data = request.get_json() or {}
    supplier_id = data.get("supplier_id")
    if not supplier_id:
        return jsonify({"error": "Fornecedor é obrigatório"}), 400
    quotation = row_to_dict(query_db("SELECT * FROM quotations WHERE id=?", [quotation_id], one=True))
    if not quotation:
        return jsonify({"error": "Cotação não encontrada"}), 404
    if quotation.get("status") not in ("open", "received"):
        return jsonify({"error": "Não é possível adicionar fornecedor a uma cotação encerrada"}), 400
    supplier = query_db("SELECT id FROM suppliers WHERE id=? AND active=1", [supplier_id], one=True)
    if not supplier:
        return jsonify({"error": "Fornecedor não encontrado ou inativo"}), 404
    existing = query_db(
        "SELECT id FROM quotation_items WHERE quotation_id=? AND supplier_id=?",
        [quotation_id, supplier_id], one=True
    )
    if existing:
        return jsonify({"error": "Fornecedor já está nesta cotação"}), 409
    item_id = str(uuid.uuid4())
    execute_db(
        "INSERT INTO quotation_items (id, quotation_id, supplier_id, unit_price, lead_time) VALUES (?,?,?,?,?)",
        [item_id, quotation_id, supplier_id, data.get("unit_price", 0), data.get("lead_time", 7)]
    )
    item = row_to_dict(query_db("SELECT * FROM quotation_items WHERE id=?", [item_id], one=True))
    return jsonify(item), 201


@suppliers_bp.route("/quotation-items/<item_id>", methods=["PUT"])
@require_role("admin", "manager", "buyer")
def update_quotation_item(item_id):
    data = request.get_json() or {}
    sets, vals = [], []
    for f in ["unit_price", "lead_time", "notes", "status"]:
        if f in data:
            sets.append(f"{f}=?")
            vals.append(data[f])
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
                [qid], one=True
            )
            if has_prices:
                execute_db("UPDATE quotations SET status='received' WHERE id=?", [qid])
    return jsonify(item)
