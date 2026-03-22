from flask import Blueprint, request, jsonify, make_response, g
from app.core.jwt_utils import create_token, jwt_required, require_role, get_current_user
from app.core.database import query_db, execute_db, row_to_dict, rows_to_dicts
from werkzeug.security import generate_password_hash, check_password_hash
import uuid

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
        return jsonify({"error": "Credenciais inválidas"}), 401
    token = create_token({"id": user["id"], "role": user["role"], "name": user["name"]})
    del user["password_hash"]
    resp = make_response(jsonify({"access_token": token, "user": user}))
    resp.set_cookie("session_token", token, httponly=True, samesite="Lax", max_age=8 * 3600)
    return resp


@auth_bp.route("/register", methods=["POST"])
@require_role("admin", "manager")
def register():
    current = get_current_user()
    data = request.get_json() or {}

    # Validate required fields
    for field in ["name", "email", "password"]:
        if not data.get(field):
            return jsonify({"error": f"Campo obrigatório: {field}"}), 400

    target_role = data.get("role", "operator")
    if target_role not in VALID_ROLES:
        return jsonify({"error": f"Perfil inválido: {target_role}"}), 400

    # Enforce role hierarchy: manager cannot create admin or other managers
    if not _can_manage_role(current.get("role", ""), target_role):
        return jsonify({"error": f"Sem permissão para criar usuários com perfil '{target_role}'"}), 403

    if query_db("SELECT id FROM users WHERE email=?", [data["email"]], one=True):
        return jsonify({"error": "Email já cadastrado"}), 400

    uid = str(uuid.uuid4())
    execute_db(
        "INSERT INTO users (id, name, email, password_hash, role) VALUES (?,?,?,?,?)",
        [uid, data["name"], data["email"], generate_password_hash(data["password"]), target_role]
    )
    user = row_to_dict(
        query_db("SELECT id, name, email, role, active, created_at FROM users WHERE id=?", [uid], one=True)
    )
    return jsonify(user), 201


@auth_bp.route("/me", methods=["GET"])
@jwt_required
def me():
    current = get_current_user()
    user = row_to_dict(
        query_db("SELECT id, name, email, role, active, created_at FROM users WHERE id=?", [current["id"]], one=True)
    )
    resp = make_response(jsonify(user))
    token = getattr(g, "current_token", "")
    if token:
        resp.set_cookie("session_token", token, httponly=True, samesite="Lax", max_age=8 * 3600)
    return resp


@auth_bp.route("/me", methods=["PUT"])
@jwt_required
def update_me():
    """Allows any authenticated user to update their own name and password."""
    current = get_current_user()
    data = request.get_json() or {}
    sets = []
    vals = []
    if data.get("name"):
        sets.append("name=?")
        vals.append(data["name"])
    if data.get("password"):
        if len(data["password"]) < 6:
            return jsonify({"error": "Senha deve ter ao menos 6 caracteres"}), 400
        sets.append("password_hash=?")
        vals.append(generate_password_hash(data["password"]))
    if not sets:
        return jsonify({"error": "Nenhum campo para atualizar"}), 400
    vals.append(current["id"])
    execute_db(f"UPDATE users SET {','.join(sets)}, updated_at=datetime('now') WHERE id=?", vals)
    user = row_to_dict(
        query_db("SELECT id, name, email, role, active, created_at FROM users WHERE id=?", [current["id"]], one=True)
    )
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
        query_db(f"SELECT id, name, email, role, active, created_at, updated_at FROM users {where} ORDER BY name", args)
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
        if len(data["password"]) < 6:
            return jsonify({"error": "Senha deve ter ao menos 6 caracteres"}), 400
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
    return jsonify(user)


@auth_bp.route("/users/<user_id>/deactivate", methods=["POST"])
@require_role("admin")
def deactivate_user(user_id):
    """Soft-delete: marks user as inactive. Admin only."""
    current = get_current_user()
    if user_id == current.get("id"):
        return jsonify({"error": "Você não pode desativar sua própria conta"}), 400
    user = row_to_dict(query_db("SELECT id, active FROM users WHERE id=?", [user_id], one=True))
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    execute_db("UPDATE users SET active=0, updated_at=datetime('now') WHERE id=?", [user_id])
    return jsonify({"message": "Usuário desativado"})


@auth_bp.route("/users/<user_id>/activate", methods=["POST"])
@require_role("admin")
def activate_user(user_id):
    """Re-activates a previously deactivated user. Admin only."""
    user = row_to_dict(query_db("SELECT id FROM users WHERE id=?", [user_id], one=True))
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    execute_db("UPDATE users SET active=1, updated_at=datetime('now') WHERE id=?", [user_id])
    return jsonify({"message": "Usuário reativado"})


@auth_bp.route("/roles", methods=["GET"])
@jwt_required
def list_roles():
    """Returns role definitions with labels, descriptions and permissions."""
    current = get_current_user()
    actor_role = current.get("role", "")

    all_roles = [
        {
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


@auth_bp.route("/logout", methods=["POST"])
def logout():
    resp = make_response(jsonify({"message": "Logout realizado"}))
    resp.delete_cookie("session_token")
    return resp
