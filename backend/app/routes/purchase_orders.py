from flask import Blueprint, request, jsonify
from app.core.jwt_utils import require_role, get_current_user
from app.core.database import query_db, execute_db, row_to_dict, rows_to_dicts, db_transaction
from app.core.audit import log_action
import uuid

po_bp = Blueprint("purchase_orders", __name__)


def next_po_number():
    row = query_db("SELECT COUNT(*) as c FROM purchase_orders", one=True)
    return f"PO-{(row['c'] + 1):05d}"


@po_bp.route("/", methods=["GET"])
@require_role("admin", "manager", "buyer")
def list_pos():
    status = request.args.get("status", "")
    q = """SELECT po.*, s.name as supplier_name, u.name as created_by_name,
                  ua.name as approved_by_name
           FROM purchase_orders po
           LEFT JOIN suppliers s ON po.supplier_id = s.id
           LEFT JOIN users u ON po.created_by = u.id
           LEFT JOIN users ua ON po.approved_by = ua.id
           WHERE 1=1"""
    args = []
    if status:
        q += " AND po.status=?"
        args.append(status)
    q += " ORDER BY po.created_at DESC"
    pos = rows_to_dicts(query_db(q, args))
    for po in pos:
        items = rows_to_dicts(query_db("""
            SELECT poi.*, p.name as product_name, p.sku as product_sku, p.unit as product_unit
            FROM purchase_order_items poi
            LEFT JOIN products p ON poi.product_id = p.id
            WHERE poi.po_id = ?
        """, [po["id"]]))
        po["items"] = items
        po["items_count"] = len(items)
    return jsonify(pos)


@po_bp.route("/<po_id>", methods=["GET"])
@require_role("admin", "manager", "buyer")
def get_po(po_id):
    po = query_db("""SELECT po.*, s.name as supplier_name, u.name as created_by_name
                     FROM purchase_orders po
                     LEFT JOIN suppliers s ON po.supplier_id = s.id
                     LEFT JOIN users u ON po.created_by = u.id
                     WHERE po.id = ?""", [po_id], one=True)
    if not po:
        return jsonify({"error": "OC não encontrada"}), 404
    po = dict(po)
    po["items"] = rows_to_dicts(query_db("""
        SELECT poi.*, p.name as product_name, p.sku as product_sku, p.unit as product_unit
        FROM purchase_order_items poi
        LEFT JOIN products p ON poi.product_id = p.id
        WHERE poi.po_id = ?
    """, [po_id]))
    return jsonify(po)


@po_bp.route("/from-quotation/<quotation_id>", methods=["POST"])
@require_role("admin", "manager", "buyer")
def create_from_quotation(quotation_id):
    """Generate a PO from an approved quotation."""
    current = get_current_user()
    quot = query_db("SELECT * FROM quotations WHERE id=? AND status='approved'",
                    [quotation_id], one=True)
    if not quot:
        return jsonify({"error": "Cotação não encontrada ou não aprovada"}), 400
    quot = dict(quot)

    # Get approved supplier item
    approved_item = query_db("""SELECT qi.*, s.name as supplier_name
                                FROM quotation_items qi
                                LEFT JOIN suppliers s ON qi.supplier_id = s.id
                                WHERE qi.quotation_id = ? AND qi.status = 'approved'""",
                             [quotation_id], one=True)
    if not approved_item:
        return jsonify({"error": "Nenhum fornecedor aprovado na cotação"}), 400
    approved_item = dict(approved_item)

    po_id = str(uuid.uuid4())
    po_number = next_po_number()

    with db_transaction():
        execute_db("""INSERT INTO purchase_orders
                      (id, po_number, quotation_id, supplier_id, status, total_value,
                       notes, expected_delivery, created_by)
                      VALUES (?,?,?,?,?,?,?,?,?)""",
                   [po_id, po_number, quotation_id, approved_item["supplier_id"],
                    "draft",
                    round(approved_item["unit_price"] * quot["quantity"], 2),
                    f"Gerada a partir da cotação #{quotation_id[:8]}",
                    None,
                    current.get("id")], commit=False)

        item_id = str(uuid.uuid4())
        execute_db("""INSERT INTO purchase_order_items
                      (id, po_id, product_id, quantity, unit_price)
                      VALUES (?,?,?,?,?)""",
                   [item_id, po_id, quot["product_id"], quot["quantity"],
                    approved_item["unit_price"]], commit=False)

    log_action("create", "purchase_order", entity_id=po_id,
               details={"po_number": po_number, "quotation_id": quotation_id,
                        "supplier": approved_item.get("supplier_name")})

    return jsonify(row_to_dict(query_db("SELECT * FROM purchase_orders WHERE id=?", [po_id], one=True))), 201


@po_bp.route("/", methods=["POST"])
@require_role("admin", "manager", "buyer")
def create_po():
    """Create a manual PO."""
    current = get_current_user()
    data = request.get_json() or {}
    supplier_id = data.get("supplier_id")
    if not supplier_id:
        return jsonify({"error": "Fornecedor é obrigatório"}), 400
    items = data.get("items", [])
    if not items:
        return jsonify({"error": "Adicione pelo menos um item"}), 400

    po_id = str(uuid.uuid4())
    po_number = next_po_number()
    total = sum(float(i.get("quantity", 0)) * float(i.get("unit_price", 0)) for i in items)

    with db_transaction():
        execute_db("""INSERT INTO purchase_orders
                      (id, po_number, supplier_id, status, total_value, notes, expected_delivery, created_by)
                      VALUES (?,?,?,?,?,?,?,?)""",
                   [po_id, po_number, supplier_id, "draft", round(total, 2),
                    data.get("notes"), data.get("expected_delivery"),
                    current.get("id")], commit=False)

        for item in items:
            execute_db("""INSERT INTO purchase_order_items
                          (id, po_id, product_id, quantity, unit_price)
                          VALUES (?,?,?,?,?)""",
                       [str(uuid.uuid4()), po_id, item["product_id"],
                        float(item.get("quantity", 0)), float(item.get("unit_price", 0))],
                       commit=False)

    log_action("create", "purchase_order", entity_id=po_id,
               details={"po_number": po_number, "supplier_id": supplier_id, "total": total})
    po = row_to_dict(query_db("SELECT * FROM purchase_orders WHERE id=?", [po_id], one=True))
    return jsonify(po), 201


@po_bp.route("/<po_id>/send", methods=["POST"])
@require_role("admin", "manager", "buyer")
def send_po(po_id):
    po = query_db("SELECT * FROM purchase_orders WHERE id=? AND status='draft'", [po_id], one=True)
    if not po:
        return jsonify({"error": "OC não encontrada ou já enviada"}), 400
    execute_db("UPDATE purchase_orders SET status='sent', updated_at=datetime('now') WHERE id=?", [po_id])
    log_action("send", "purchase_order", entity_id=po_id)
    return jsonify({"message": "OC enviada ao fornecedor"})


@po_bp.route("/<po_id>/receive", methods=["POST"])
@require_role("admin", "manager", "operator")
def receive_po(po_id):
    """Mark PO items as received and create stock entries."""
    current = get_current_user()
    po = query_db("SELECT * FROM purchase_orders WHERE id=? AND status IN ('sent','partial')",
                  [po_id], one=True)
    if not po:
        return jsonify({"error": "OC não encontrada ou já recebida"}), 400
    po = dict(po)

    data = request.get_json() or {}
    received_items = data.get("items", [])
    invoice_id = data.get("invoice_id")

    items = rows_to_dicts(query_db("SELECT * FROM purchase_order_items WHERE po_id=?", [po_id]))

    with db_transaction():
        all_received = True
        for item in items:
            recv = next((r for r in received_items if r.get("item_id") == item["id"]), None)
            recv_qty = float(recv.get("received_quantity", 0)) if recv else 0
            if recv_qty <= 0:
                if item["received_quantity"] < item["quantity"]:
                    all_received = False
                continue

            new_recv = min(item["received_quantity"] + recv_qty, item["quantity"])
            execute_db("UPDATE purchase_order_items SET received_quantity=? WHERE id=?",
                       [new_recv, item["id"]], commit=False)

            if new_recv < item["quantity"]:
                all_received = False

            # Create stock entry movement
            mid = str(uuid.uuid4())
            execute_db("""INSERT INTO movements
                          (id, product_id, type, quantity, unit_cost, user_id, supplier_id,
                           invoice_id, observation)
                          VALUES (?,?,?,?,?,?,?,?,?)""",
                       [mid, item["product_id"], "entry", recv_qty,
                        item["unit_price"], current.get("id"),
                        po["supplier_id"], invoice_id,
                        f"Recebimento OC {po['po_number']}"], commit=False)
            execute_db("UPDATE products SET stock=stock+?, updated_at=datetime('now') WHERE id=?",
                       [recv_qty, item["product_id"]], commit=False)

        new_status = "received" if all_received else "partial"
        updates = "status=?, updated_at=datetime('now')"
        params = [new_status, po_id]
        if invoice_id:
            updates = "status=?, invoice_id=?, updated_at=datetime('now')"
            params = [new_status, invoice_id, po_id]
        execute_db(f"UPDATE purchase_orders SET {updates} WHERE id=?", params, commit=False)

    log_action("receive", "purchase_order", entity_id=po_id,
               details={"status": new_status, "invoice_id": invoice_id})
    return jsonify({"message": f"OC atualizada — status: {new_status}", "status": new_status})


@po_bp.route("/<po_id>/cancel", methods=["POST"])
@require_role("admin", "manager")
def cancel_po(po_id):
    po = query_db("SELECT * FROM purchase_orders WHERE id=? AND status IN ('draft','sent')",
                  [po_id], one=True)
    if not po:
        return jsonify({"error": "OC não encontrada ou não pode ser cancelada"}), 400
    execute_db("UPDATE purchase_orders SET status='cancelled', updated_at=datetime('now') WHERE id=?", [po_id])
    log_action("cancel", "purchase_order", entity_id=po_id)
    return jsonify({"message": "OC cancelada"})
