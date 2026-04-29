from flask import Blueprint, abort, redirect, render_template, request

from app.middleware import load_jwt_user


pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/")
@pages_bp.route("/alerts")
@pages_bp.route("/rotations")
@pages_bp.route("/calendar")
@pages_bp.route("/routes")
@pages_bp.route("/channels")
@pages_bp.route("/silences")
@pages_bp.route("/teams")
@pages_bp.route("/groups")
@pages_bp.route("/profile")
@pages_bp.route("/admin/users")
@pages_bp.route("/login")
def app_page():
    """
    Render the frontend application for direct page URLs.
    """

    user = load_jwt_user()

    if request.path == "/login":
        if user:
            return redirect("/")
        return render_template("login_only.html")

    if not user:
        return redirect("/login")

    if request.path in ("/admin/users", "/groups") and not user.is_admin:
        abort(403)

    return render_template("index.html", initial_page=request.path)
