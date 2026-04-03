"""
Audit logging helper.

All persistent mutations in the system call log_action() to record a trail
of who did what and when.  Failures are swallowed silently so that audit
logging never disrupts the main operation.
"""

import uuid
import json
from flask import g, request
from app.core.database import execute_db


def log_action(
    action: str,
    entity_type: str,
    entity_id: str = None,
    details: dict = None,
    user_id: str = None,
):
    """
    Write a row to audit_logs.

    Parameters
    ----------
    action      : verb describing the operation, e.g.
                  'create' | 'update' | 'delete' | 'login' | 'login_failed'
                  'entry'  | 'exit'   | 'adjustment'
                  'process_invoice' | 'reverse_invoice' | 'import_invoice'
                  'run_match' | 'approve_quotation' | 'create_quotation'
                  'deactivate_user' | 'activate_user' | 'change_password'
    entity_type : noun, e.g. 'user' | 'product' | 'category' | 'movement'
                  'project' | 'project_need' | 'invoice' | 'supplier'
                  'quotation' | 'quotation_item'
    entity_id   : UUID of the affected record (may be None for bulk ops)
    details     : dict of relevant fields to store as JSON snapshot
    user_id     : override; if omitted, resolved from g.current_user
    """
    if user_id is None:
        current = getattr(g, "current_user", {})
        user_id = current.get("id")

    try:
        # Best-effort IP resolution (works behind Nginx with X-Forwarded-For)
        ip = None
        try:
            ip = request.headers.get("X-Forwarded-For", request.remote_addr)
            if ip and "," in ip:
                ip = ip.split(",")[0].strip()
        except RuntimeError:
            pass  # Outside request context

        execute_db(
            """INSERT INTO audit_logs
               (id, user_id, action, entity_type, entity_id, details, ip_address)
               VALUES (?,?,?,?,?,?,?)""",
            [
                str(uuid.uuid4()),
                user_id,
                action,
                entity_type,
                entity_id,
                json.dumps(details, ensure_ascii=False, default=str) if details else None,
                ip,
            ],
        )
    except Exception:
        pass  # Never let audit logging break the main operation
