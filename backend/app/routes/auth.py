from flask import Blueprint, request, jsonify, make_response, g
from app.core.jwt_utils import create_token, jwt_required, require_role, get_current_user
from app.core.database import query_db, execute_db, row_to_dict, rows_to_dicts
from app.core.audit import log_action
from werkzeug.security import generate_password_hash, check_password_hash
import uuid

# Minimum password length enforced system-wide
_MIN_PASSWORD_LEN = 8

def _validate_password_complexity(password: str) -> tuple[bool, str]:
    if len(password) < _MIN_PASSWORD_LEN:
        return False, f"A senha deve ter ao menos {_MIN_PASSWORD_LEN} caracteres"
    if not any(c.isupper() for c in password):
        return False, "A senha deve conter ao menos uma letra maiúscula"
    if not any(c.islower() for c in password):
        return False, "A senha deve conter ao menos uma letra minúscula"
    if not any(c.isdigit() for c in password):
        return False, "A senha deve conter ao menos um número"
    return True, ""

auth_bp = Blueprint("auth", __name__)

# Roles permitidas para criação
VALID_ROLES = {"admin", "manager", "operator", "buyer"}

# Matrix de permissões: quais roles cada role pode criar/gerenciar
# admin pode gerenciar todos; manager pode gerenciar operator e buyer
ROLE_CAN_MANAGE = {
    "admin":   {"admin", "manager", "operator", "buyer"},
    "manager": {"operator", "buyer"},
}


def _can_manage_role(actor_role: str, target_role: str) -> bool:
    allowed = ROLE_CAN_MANAGE.get(actor_role, set())
    return target_role in allowed


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data or not data.get("email") or not data.get("password"):
        return jsonify({"error": "Email e senha obrigatórios"}), 400
    user = row_to_dict(
        query_db("SELECT * FROM users WHERE email=? AND active=1", [data["email"]], one=True)
    )
    if not user or not check_password_hash(user["password_hash"], data["password"]):
        # Log failed attempt without exposing which part failed
        log_action(
            "login_failed", "user",
            details={"email": data.get("email")},
            user_id=user.get("id") if user else None,
        )
        return jsonify({"error": "Credenciais inválidas"}), 401

    # Update last_login timestamp
    execute_db(
        "UPDATE users SET last_login=datetime('now') WHERE id=?",
        [user["id"]]
    )

    token = create_token({"id": user["id"], "role": user["role"], "name": user["name"]})
    log_action("login", "user", entity_id=user["id"],
               details={"name": user["name"], "role": user["role"]},
               user_id=user["id"])

    del user["password_hash"]
    user["must_change_password"] = bool(user.get("must_change_password"))
    resp = make_response(jsonify({"access_token": token, "user": user}))
    # LGPD/Security: Setting cookie with Secure and SameSite flags
    # In production, secure=True should be used (requires HTTPS)
    is_prod = request.host.endswith('herokuapp.com') or not request.host.startswith('localhost')
    resp.set_cookie("session_token", token, 
                    httponly=True, 
                    secure=is_prod, 
                    samesite="Lax", 
                    max_age=8 * 3600)
    return resp


@auth_bp.route("/register", methods=["POST"])
@require_role("admin", "manager")
def register():
    current = get_current_user()
    data = request.get_json() or {}

    # Validate required fields
    if not data.get("name") or not data.get("email") or not data.get("password"):
        return jsonify({"error": "Nome, email e senha são obrigatórios"}), 400

    is_valid, error_msg = _validate_password_complexity(data["password"])
    if not is_valid:
        return jsonify({"error": error_msg}), 400

    target_role = data.get("role", "operator")
    if target_role not in VALID_ROLES:
        return jsonify({"error": f"Perfil inválido: {target_role}"}), 400

    # Enforce role hierarchy: manager cannot create admin or other managers
    if not _can_manage_role(current.get("role", ""), target_role):
        return jsonify({"error": f"Sem permissão para criar usuários com perfil '{target_role}'"}), 403

    if query_db("SELECT id FROM users WHERE email=?", [data["email"]], one=True):
        return jsonify({"error": "Email já cadastrado"}), 409

    uid = str(uuid.uuid4())
    execute_db(
        "INSERT INTO users (id, name, email, password_hash, role) VALUES (?,?,?,?,?)",
        [uid, data["name"], data["email"], generate_password_hash(data["password"]), target_role]
    )
    user = row_to_dict(
        query_db("SELECT id, name, email, role, active, created_at FROM users WHERE id=?", [uid], one=True)
    )
    log_action("create", "user", entity_id=uid,
               details={"name": data["name"], "email": data["email"], "role": target_role})
    return jsonify(user), 201


@auth_bp.route("/me", methods=["GET"])
@jwt_required
def me():
    current = get_current_user()
    user = row_to_dict(
        query_db("SELECT id, name, email, role, active, created_at, last_login FROM users WHERE id=?", [current["id"]], one=True)
    )
    resp = make_response(jsonify(user))
    token = getattr(g, "current_token", "")
    if token:
        resp.set_cookie("session_token", token, httponly=True, samesite="Lax", max_age=8 * 3600)
    return resp


@auth_bp.route("/me", methods=["PUT"])
@jwt_required
def update_me():
    """Allows any authenticated user to update their own name, email and password."""
    current = get_current_user()
    user_db = row_to_dict(
        query_db("SELECT * FROM users WHERE id=?", [current["id"]], one=True)
    )
    if not user_db:
        return jsonify({"error": "Usuário não encontrado"}), 404

    data = request.get_json() or {}
    sets = []
    vals = []
    if data.get("name"):
        sets.append("name=?")
        vals.append(data["name"])
    if data.get("email"):
        new_email = data["email"].strip().lower()
        if new_email != user_db["email"]:
            if query_db("SELECT id FROM users WHERE email=? AND id!=?", [new_email, current["id"]], one=True):
                return jsonify({"error": "Email já cadastrado por outro usuário"}), 400
            sets.append("email=?")
            vals.append(new_email)
    # Suporta tanto "new_password"+"current_password" quanto o campo legado "password"
    new_pwd = data.get("new_password") or data.get("password")
    if new_pwd:
        if data.get("new_password"):
            # Valida senha atual antes de trocar
            if not check_password_hash(user_db["password_hash"], data.get("current_password", "")):
                return jsonify({"error": "Senha atual incorreta"}), 400
        is_valid, error_msg = _validate_password_complexity(new_pwd)
        if not is_valid:
            return jsonify({"error": error_msg}), 400
        sets.append("password_hash=?")
        vals.append(generate_password_hash(new_pwd))
    if not sets:
        return jsonify({"error": "Nenhum campo para atualizar"}), 400
    # Clear must_change_password whenever email or password is updated
    if any(s.startswith("password_hash") or s.startswith("email") for s in sets):
        sets.append("must_change_password=?")
        vals.append(0)
    vals.append(current["id"])
    execute_db(f"UPDATE users SET {','.join(sets)}, updated_at=datetime('now') WHERE id=?", vals)
    user = row_to_dict(
        query_db("SELECT id, name, email, role, active, created_at, must_change_password FROM users WHERE id=?", [current["id"]], one=True)
    )
    user["must_change_password"] = bool(user.get("must_change_password"))
    changed = {}
    if data.get("name"): changed["name"] = data["name"]
    if data.get("password") or data.get("new_password"): changed["password_changed"] = True
    if data.get("email"): changed["email_changed"] = True
    log_action("update", "user", entity_id=current["id"], details=changed)
    return jsonify(user)


@auth_bp.route("/users", methods=["GET"])
@require_role("admin", "manager")
def list_users():
    """
    Lists users. Admins see all users (including inactive).
    Managers see only active operator/buyer accounts.
    Accepts ?include_inactive=1 (admin only) and ?role= filter.
    """
    current = get_current_user()
    actor_role = current.get("role", "")

    include_inactive = request.args.get("include_inactive") == "1" and actor_role == "admin"
    role_filter = request.args.get("role", "")

    conditions = []
    args = []

    if not include_inactive:
        conditions.append("active=1")

    # Managers only see roles they can manage
    if actor_role == "manager":
        conditions.append("role IN ('operator','buyer')")
    elif role_filter and role_filter in VALID_ROLES:
        conditions.append("role=?")
        args.append(role_filter)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    users = rows_to_dicts(
        query_db(f"SELECT id, name, email, role, active, last_login, created_at, updated_at FROM users {where} ORDER BY name", args)
    )
    return jsonify(users)


@auth_bp.route("/users/<user_id>", methods=["GET"])
@require_role("admin", "manager")
def get_user(user_id):
    current = get_current_user()
    user = row_to_dict(
        query_db("SELECT id, name, email, role, active, created_at, updated_at FROM users WHERE id=?", [user_id], one=True)
    )
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    # Manager can only view operator/buyer
    if current.get("role") == "manager" and user["role"] not in ("operator", "buyer"):
        return jsonify({"error": "Acesso negado"}), 403
    return jsonify(user)


@auth_bp.route("/users/<user_id>", methods=["PUT"])
@require_role("admin", "manager")
def update_user(user_id):
    current = get_current_user()
    actor_role = current.get("role", "")

    target = row_to_dict(
        query_db("SELECT id, name, email, role, active FROM users WHERE id=?", [user_id], one=True)
    )
    if not target:
        return jsonify({"error": "Usuário não encontrado"}), 404

    # Prevent managing users outside allowed hierarchy
    if not _can_manage_role(actor_role, target["role"]):
        return jsonify({"error": "Sem permissão para editar este usuário"}), 403

    # Admin cannot deactivate themselves
    if user_id == current.get("id") and "active" in (request.get_json() or {}):
        if not (request.get_json() or {}).get("active", True):
            return jsonify({"error": "Você não pode desativar sua própria conta"}), 400

    data = request.get_json() or {}
    sets = []
    vals = []

    if "name" in data and data["name"]:
        sets.append("name=?")
        vals.append(data["name"])

    if "email" in data and data["email"]:
        new_email = data["email"].strip().lower()
        if new_email != target["email"]:
            if query_db("SELECT id FROM users WHERE email=? AND id!=?", [new_email, user_id], one=True):
                return jsonify({"error": "Email já cadastrado por outro usuário"}), 400
            sets.append("email=?")
            vals.append(new_email)

    if "role" in data:
        new_role = data["role"]
        if new_role not in VALID_ROLES:
            return jsonify({"error": f"Perfil inválido: {new_role}"}), 400
        # Cannot promote to a role you cannot manage
        if not _can_manage_role(actor_role, new_role):
            return jsonify({"error": f"Sem permissão para atribuir perfil '{new_role}'"}), 403
        sets.append("role=?")
        vals.append(new_role)

    if "active" in data:
        sets.append("active=?")
        vals.append(1 if data["active"] else 0)

    if "password" in data and data["password"]:
        is_valid, error_msg = _validate_password_complexity(data["password"])
        if not is_valid:
            return jsonify({"error": error_msg}), 400
        sets.append("password_hash=?")
        vals.append(generate_password_hash(data["password"]))

    if not sets:
        return jsonify({"error": "Nenhum campo para atualizar"}), 400

    sets.append("updated_at=datetime('now')")
    vals.append(user_id)
    execute_db(f"UPDATE users SET {','.join(sets)} WHERE id=?", vals)
    user = row_to_dict(
        query_db("SELECT id, name, email, role, active, created_at, updated_at FROM users WHERE id=?", [user_id], one=True)
    )
    # Build audit detail (never log new password)
    changed = {k: data[k] for k in ("name", "role", "active") if k in data}
    if "password" in data and data["password"]:
        changed["password_changed"] = True
    log_action("update", "user", entity_id=user_id, details=changed)
    return jsonify(user)


@auth_bp.route("/users/<user_id>/deactivate", methods=["POST"])
@require_role("admin")
def deactivate_user(user_id):
    """Soft-delete: marks user as inactive. Admin only."""
    current = get_current_user()
    if user_id == current.get("id"):
        return jsonify({"error": "Você não pode desativar sua própria conta"}), 400
    user = row_to_dict(query_db("SELECT id, name, role, active FROM users WHERE id=?", [user_id], one=True))
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    execute_db("UPDATE users SET active=0, updated_at=datetime('now') WHERE id=?", [user_id])
    log_action("deactivate_user", "user", entity_id=user_id,
               details={"name": user.get("name"), "role": user.get("role")})
    return jsonify({"message": "Usuário desativado"})


@auth_bp.route("/users/<user_id>/activate", methods=["POST"])
@require_role("admin")
def activate_user(user_id):
    """Re-activates a previously deactivated user. Admin only."""
    user = row_to_dict(query_db("SELECT id FROM users WHERE id=?", [user_id], one=True))
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    execute_db("UPDATE users SET active=1, updated_at=datetime('now') WHERE id=?", [user_id])
    log_action("activate_user", "user", entity_id=user_id)
    return jsonify({"message": "Usuário reativado"})


@auth_bp.route("/roles", methods=["GET"])
@jwt_required
def list_roles():
    """Returns role definitions with labels, descriptions and permissions."""
    current = get_current_user()
    actor_role = current.get("role", "")

    all_roles = [
        {
            "id": "admin",
            "value": "admin",
            "label": "Administrador",
            "description": "Acesso total ao sistema. Gerencia usuários, configurações e pode estornar operações.",
            "color": "badge-danger",
            "permissions": [
                "Gerenciar usuários e perfis",
                "Criar/editar/excluir produtos",
                "Registrar movimentações (entrada, saída, ajuste)",
                "Importar NF-e (XML e PDF)",
                "Processar e estornar notas fiscais",
                "Gerenciar projetos e necessidades",
                "Gerenciar fornecedores e cotações",
                "Visualizar relatórios e dashboard",
            ]
        },
        {
            "id": "manager",
            "value": "manager",
            "label": "Gerente",
            "description": "Acesso gerencial. Aprova operações, visualiza relatórios e gerencia operadores.",
            "color": "badge-purple",
            "permissions": [
                "Criar/editar operadores e compradores",
                "Criar/editar/excluir produtos",
                "Registrar movimentações (entrada, saída, ajuste)",
                "Importar NF-e (XML e PDF)",
                "Processar notas fiscais",
                "Gerenciar projetos e necessidades",
                "Gerenciar fornecedores e cotações",
                "Aprovar cotações de fornecedores",
                "Visualizar relatórios e dashboard",
            ]
        },
        {
            "id": "operator",
            "value": "operator",
            "label": "Operador",
            "description": "Acesso operacional. Movimenta estoque e consulta produtos e projetos.",
            "color": "badge-info",
            "permissions": [
                "Visualizar produtos e estoque",
                "Registrar movimentações de entrada e saída",
                "Visualizar movimentações",
                "Visualizar projetos e necessidades",
                "Visualizar fornecedores",
                "Visualizar notas fiscais",
                "Visualizar dashboard",
            ]
        },
        {
            "id": "buyer",
            "value": "buyer",
            "label": "Compras",
            "description": "Acesso ao módulo de compras. Gerencia fornecedores, cotações e importa notas.",
            "color": "badge-warning",
            "permissions": [
                "Importar NF-e (XML e PDF)",
                "Gerenciar fornecedores e cotações",
                "Criar e aprovar cotações",
                "Visualizar produtos e estoque",
                "Visualizar projetos e necessidades",
                "Visualizar dashboard",
            ]
        },
    ]

    # Filter roles based on what the actor can manage (for create/edit forms)
    manageable = ROLE_CAN_MANAGE.get(actor_role, set())
    for role in all_roles:
        role["can_assign"] = role["value"] in manageable

    return jsonify(all_roles)


@auth_bp.route("/users/<user_id>/activity", methods=["GET"])
@require_role("admin", "manager")
def user_activity(user_id):
    """
    Returns a consolidated activity timeline for a specific user.
    Includes:
      - audit_logs authored by this user (all actions)
      - movements registered by this user (entry/exit/adjustment)
    Query params:
      date_from, date_to  – ISO date range (YYYY-MM-DD, inclusive)
      type                – 'audit' | 'movement' | '' (both)
      limit               – max rows per type (default 200)
    """
    current = get_current_user()
    # Manager can only view operator/buyer activity
    target = row_to_dict(
        query_db("SELECT id, name, email, role, active, last_login, created_at FROM users WHERE id=?",
                 [user_id], one=True)
    )
    if not target:
        return jsonify({"error": "Usuário não encontrado"}), 404
    if current.get("role") == "manager" and target["role"] not in ("operator", "buyer"):
        return jsonify({"error": "Acesso negado"}), 403

    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    filter_type = request.args.get("type", "")
    try:
        limit = min(int(request.args.get("limit", 200)), 1000)
    except (TypeError, ValueError):
        limit = 200

    # ── Audit logs ──────────────────────────────────────────────
    audit_items = []
    if filter_type in ("", "audit"):
        aq = """
            SELECT 'audit' as source, al.id, al.action, al.entity_type, al.entity_id,
                   al.details, al.ip_address, al.created_at
            FROM audit_logs al
            WHERE al.user_id=?
        """
        aa = [user_id]
        if date_from:
            aq += " AND date(al.created_at) >= date(?)"; aa.append(date_from)
        if date_to:
            aq += " AND date(al.created_at) <= date(?)"; aa.append(date_to)
        aq += f" ORDER BY al.created_at DESC LIMIT {limit}"
        rows = query_db(aq, aa)
        for r in rows:
            d = dict(r)
            audit_items.append(d)

    # ── Movements ───────────────────────────────────────────────
    movement_items = []
    if filter_type in ("", "movement"):
        mq = """
            SELECT 'movement' as source, m.id, m.type as action, m.product_id,
                   p.name as product_name, p.unit as product_unit,
                   m.quantity, m.unit_cost, m.invoice_number,
                   m.observation, m.created_at,
                   pr.name as project_name
            FROM movements m
            LEFT JOIN products p ON m.product_id = p.id
            LEFT JOIN projects pr ON m.project_id = pr.id
            WHERE m.user_id=?
        """
        ma = [user_id]
        if date_from:
            mq += " AND date(m.created_at) >= date(?)"; ma.append(date_from)
        if date_to:
            mq += " AND date(m.created_at) <= date(?)"; ma.append(date_to)
        mq += f" ORDER BY m.created_at DESC LIMIT {limit}"
        rows = query_db(mq, ma)
        for r in rows:
            movement_items.append(dict(r))

    # ── Summary stats ────────────────────────────────────────────
    stats = {}
    if filter_type in ("", "movement"):
        mv_stats = query_db(
            """SELECT type, COUNT(*) as count, COALESCE(SUM(ABS(quantity)),0) as total_qty
               FROM movements WHERE user_id=? GROUP BY type""",
            [user_id]
        )
        stats["movements"] = {r["type"]: {"count": r["count"], "total_qty": r["total_qty"]}
                               for r in mv_stats}
    if filter_type in ("", "audit"):
        al_stats = query_db(
            """SELECT action, COUNT(*) as count FROM audit_logs
               WHERE user_id=? GROUP BY action ORDER BY count DESC""",
            [user_id]
        )
        stats["audit_actions"] = {r["action"]: r["count"] for r in al_stats}

    return jsonify({
        "user": target,
        "stats": stats,
        "audit": audit_items,
        "movements": movement_items,
    })


@auth_bp.route("/logout", methods=["POST"])
def logout():
    resp = make_response(jsonify({"message": "Logout realizado"}))
    resp.delete_cookie("session_token")
    return resp
