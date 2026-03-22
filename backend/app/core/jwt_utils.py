import jwt
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify, redirect, current_app, g


def create_token(payload: dict) -> str:
    data = {**payload, "exp": datetime.utcnow() + timedelta(hours=8)}
    return jwt.encode(data, current_app.config["JWT_SECRET_KEY"], algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, current_app.config["JWT_SECRET_KEY"], algorithms=["HS256"])


def jwt_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing token"}), 401
        token = auth_header[7:]
        try:
            payload = decode_token(token)
            g.current_user = payload
            g.current_token = token
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    return getattr(g, "current_user", {})


def page_login_required(f):
    """Decorator para rotas HTML: valida o cookie session_token e redireciona para /login se invalido."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("session_token", "")
        if not token:
            return redirect("/login")
        try:
            payload = decode_token(token)
            g.current_user = payload
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated


def require_role(*roles):
    """Decorator que exige autenticacao JWT e que o role do usuario esteja na lista permitida."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return jsonify({"error": "Missing token"}), 401
            token = auth_header[7:]
            try:
                payload = decode_token(token)
                g.current_user = payload
                g.current_token = token
            except jwt.ExpiredSignatureError:
                return jsonify({"error": "Token expired"}), 401
            except jwt.InvalidTokenError:
                return jsonify({"error": "Invalid token"}), 401
            if payload.get("role") not in roles:
                return jsonify({"error": "Acesso negado: permissao insuficiente"}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator
