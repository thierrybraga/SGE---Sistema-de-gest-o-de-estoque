import os
from flask import Flask, request

def _env_enabled(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

def create_app(config_name="development"):
    app = Flask(__name__, template_folder="templates", static_folder="static")

    from app.core.config import config_map
    app.config.from_object(config_map[config_name])

    if config_name == "production":
        default_secret = "stock-enterprise-secret-2024"
        default_jwt = "jwt-stock-secret-2024"
        if app.config.get("SECRET_KEY") == default_secret or app.config.get("JWT_SECRET_KEY") == default_jwt:
            raise RuntimeError("SECRET_KEY e JWT_SECRET_KEY devem ser definidos em produção")

    if _env_enabled(os.environ.get("CORS_ENABLED")):
        try:
            from flask_cors import CORS
            origins_env = os.environ.get("CORS_ORIGINS", "")
            origins = [o.strip() for o in origins_env.split(",") if o.strip()] if origins_env else None
            CORS(app, supports_credentials=True, origins=origins)
        except ImportError:
            pass

    from app.core.database import init_db
    with app.app_context():
        init_db(app)

    from app.routes.auth import auth_bp
    from app.routes.products import products_bp
    from app.routes.movements import movements_bp
    from app.routes.projects import projects_bp
    from app.routes.suppliers import suppliers_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.invoices import invoices_bp
    from app.routes.audit import audit_bp
    from app.routes.tools import tools_bp
    from app.routes.frontend import frontend_bp
    from app.routes.purchase_orders import po_bp
    from app.routes.inventory import inventory_bp

    app.register_blueprint(frontend_bp)
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(products_bp, url_prefix="/api/products")
    app.register_blueprint(movements_bp, url_prefix="/api/movements")
    app.register_blueprint(projects_bp, url_prefix="/api/projects")
    app.register_blueprint(suppliers_bp, url_prefix="/api/suppliers")
    app.register_blueprint(dashboard_bp, url_prefix="/api/dashboard")
    app.register_blueprint(invoices_bp, url_prefix="/api/invoices")
    app.register_blueprint(audit_bp, url_prefix="/api/audit")
    app.register_blueprint(tools_bp, url_prefix="/api/tools")
    app.register_blueprint(po_bp, url_prefix="/api/purchase-orders")
    app.register_blueprint(inventory_bp, url_prefix="/api/inventory")

    # Global caching and security headers (LGPD/Best Practices)
    @app.after_request
    def add_headers(response):
        # Prevent sensitive data caching on API and Auth routes
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
        else:
            # Allow static caching for 1 day for non-API assets
            if response.mimetype and (response.mimetype.startswith('image/') or 
                                      response.mimetype == 'text/css' or 
                                      response.mimetype == 'application/javascript'):
                response.headers['Cache-Control'] = 'public, max-age=86400'
        
        # Security Headers
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        return response

    return app
