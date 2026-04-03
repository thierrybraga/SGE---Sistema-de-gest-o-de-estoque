from flask import Blueprint, render_template
from app.core.jwt_utils import page_login_required

frontend_bp = Blueprint("frontend", __name__)


@frontend_bp.route("/")
@frontend_bp.route("/login")
def login_page():
    return render_template("login.html")


@frontend_bp.route("/dashboard")
@page_login_required
def dashboard_page():
    return render_template("dashboard.html")


@frontend_bp.route("/products")
@page_login_required
def products_page():
    return render_template("products.html")


@frontend_bp.route("/movements")
@page_login_required
def movements_page():
    return render_template("movements.html")


@frontend_bp.route("/projects")
@page_login_required
def projects_page():
    return render_template("projects.html")


@frontend_bp.route("/suppliers")
@page_login_required
def suppliers_page():
    return render_template("suppliers.html")


@frontend_bp.route("/invoices")
@page_login_required
def invoices_page():
    return render_template("invoices.html")


@frontend_bp.route("/users")
@page_login_required
def users_page():
    return render_template("users.html")


@frontend_bp.route("/reports")
@page_login_required
def reports_page():
    return render_template("reports.html")


@frontend_bp.route("/tools")
@page_login_required
def tools_page():
    return render_template("tools.html")


@frontend_bp.route("/mobile/tools")
@page_login_required
def mobile_tools_page():
    return render_template("mobile_tools.html")


@frontend_bp.route("/mobile/inventory")
@page_login_required
def mobile_inventory_page():
    return render_template("mobile_inventory.html")


@frontend_bp.route("/purchase-orders")
@page_login_required
def purchase_orders_page():
    return render_template("purchase_orders.html")


@frontend_bp.route("/inventory-check")
@page_login_required
def inventory_check_page():
    return render_template("inventory_check.html")
