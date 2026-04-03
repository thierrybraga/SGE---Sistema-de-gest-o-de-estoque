from flask import Blueprint, request, jsonify
from app.core.jwt_utils import require_role
from app.core.database import query_db, rows_to_dicts

audit_bp = Blueprint("audit", __name__)

# Human-readable labels for the frontend
ACTION_LABELS = {
    "create": "Criação",
    "update": "Edição",
    "delete": "Exclusão",
    "login": "Login",
    "login_failed": "Falha de login",
    "change_password": "Senha alterada",
    "deactivate_user": "Usuário desativado",
    "activate_user": "Usuário reativado",
    "entry": "Entrada de estoque",
    "exit": "Saída de estoque",
    "adjustment": "Ajuste de estoque",
    "import_invoice": "Importação de NF",
    "process_invoice": "Processamento de NF",
    "reverse_invoice": "Estorno de NF",
    "run_match": "Match de estoque",
    "create_quotation": "Cotação criada",
    "approve_quotation": "Cotação aprovada",
}

ENTITY_LABELS = {
    "user": "Usuário",
    "product": "Produto",
    "category": "Categoria",
    "movement": "Movimentação",
    "project": "Projeto",
    "project_need": "Necessidade",
    "invoice": "Nota Fiscal",
    "supplier": "Fornecedor",
    "quotation": "Cotação",
    "quotation_item": "Item de Cotação",
}


@audit_bp.route("/", methods=["GET"])
@require_role("admin", "manager")
def list_logs():
    """
    Query audit logs with optional filters.
    Query params:
        user_id      – filter by actor
        action       – exact action string
        entity_type  – exact entity_type string
        entity_id    – exact entity_id UUID
        date_from    – ISO date YYYY-MM-DD  (inclusive)
        date_to      – ISO date YYYY-MM-DD  (inclusive)
        limit        – max rows (default 200, max 1000)
        offset       – pagination offset (default 0)
    """
    q = """
        SELECT al.*,
               u.name  AS user_name,
               u.email AS user_email,
               u.role  AS user_role
        FROM audit_logs al
        LEFT JOIN users u ON al.user_id = u.id
        WHERE 1=1
    """
    args = []

    if request.args.get("user_id"):
        q += " AND al.user_id=?"; args.append(request.args["user_id"])
    if request.args.get("action"):
        q += " AND al.action=?"; args.append(request.args["action"])
    if request.args.get("entity_type"):
        q += " AND al.entity_type=?"; args.append(request.args["entity_type"])
    if request.args.get("entity_id"):
        q += " AND al.entity_id=?"; args.append(request.args["entity_id"])
    if request.args.get("date_from"):
        q += " AND date(al.created_at) >= date(?)"; args.append(request.args["date_from"])
    if request.args.get("date_to"):
        q += " AND date(al.created_at) <= date(?)"; args.append(request.args["date_to"])

    q += " ORDER BY al.created_at DESC"

    try:
        limit = min(int(request.args.get("limit", 200)), 1000)
    except (TypeError, ValueError):
        limit = 200
    try:
        offset = max(int(request.args.get("offset", 0)), 0)
    except (TypeError, ValueError):
        offset = 0

    q += f" LIMIT {limit} OFFSET {offset}"

    rows = query_db(q, args)
    result = []
    for row in rows:
        d = dict(row)
        d["action_label"] = ACTION_LABELS.get(d.get("action", ""), d.get("action", ""))
        d["entity_label"] = ENTITY_LABELS.get(d.get("entity_type", ""), d.get("entity_type", ""))
        result.append(d)

    return jsonify(result)


@audit_bp.route("/summary", methods=["GET"])
@require_role("admin", "manager")
def log_summary():
    """Returns aggregated counts for the last 30 days, grouped by action."""
    rows = query_db(
        """
        SELECT action, COUNT(*) as count
        FROM audit_logs
        WHERE datetime(created_at) >= datetime('now', '-30 days')
        GROUP BY action
        ORDER BY count DESC
        """
    )
    return jsonify(rows_to_dicts(rows))


@audit_bp.route("/entity/<entity_type>/<entity_id>", methods=["GET"])
@require_role("admin", "manager")
def entity_history(entity_type, entity_id):
    """Returns full history of actions on a specific entity."""
    rows = query_db(
        """
        SELECT al.*, u.name AS user_name, u.role AS user_role
        FROM audit_logs al
        LEFT JOIN users u ON al.user_id = u.id
        WHERE al.entity_type=? AND al.entity_id=?
        ORDER BY al.created_at ASC
        """,
        [entity_type, entity_id],
    )
    result = []
    for row in rows:
        d = dict(row)
        d["action_label"] = ACTION_LABELS.get(d.get("action", ""), d.get("action", ""))
        result.append(d)
    return jsonify(result)
