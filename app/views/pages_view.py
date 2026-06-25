from flask import (
    Blueprint,
    abort,
    current_app,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
)

from app.middleware import load_jwt_user


pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/manifest.webmanifest")
def pwa_manifest():
    """Serve PWA manifest with correct content type."""
    return send_from_directory(
        current_app.static_folder,
        "manifest.webmanifest",
        mimetype="application/manifest+json",
    )


@pages_bp.route("/service-worker.js")
def pwa_service_worker():
    """Serve service worker from app root so it can control the whole app."""
    response = make_response(
        send_from_directory(
            current_app.static_folder,
            "service-worker.js",
            mimetype="application/javascript",
        )
    )
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@pages_bp.route("/")
@pages_bp.route("/alerts")
@pages_bp.route("/alerts/")
@pages_bp.route("/alerts/<int:alert_id>")
@pages_bp.route("/rotations")
@pages_bp.route("/rotations/")
@pages_bp.route("/calendar")
@pages_bp.route("/calendar/")
@pages_bp.route("/routes")
@pages_bp.route("/routes/")
@pages_bp.route("/services")
@pages_bp.route("/services/")
@pages_bp.route("/maintenance-windows")
@pages_bp.route("/maintenance-windows/")
@pages_bp.route("/escalation-policies")
@pages_bp.route("/escalation-policies/")
@pages_bp.route("/notification-policies")
@pages_bp.route("/notification-policies/")
@pages_bp.route("/matcher-presets")
@pages_bp.route("/matcher-presets/")
@pages_bp.route("/priority-policies")
@pages_bp.route("/priority-policies/")
@pages_bp.route("/channels")
@pages_bp.route("/channels/")
@pages_bp.route("/silences")
@pages_bp.route("/silences/")
@pages_bp.route("/teams")
@pages_bp.route("/teams/")
@pages_bp.route("/groups")
@pages_bp.route("/groups/")
@pages_bp.route("/profile")
@pages_bp.route("/profile/")
@pages_bp.route("/admin/users")
@pages_bp.route("/admin/users/")
@pages_bp.route("/admin/sso")
@pages_bp.route("/admin/sso/")
@pages_bp.route("/login")
def app_page(alert_id=None):
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

    if request.path in ("/admin/users", "/groups", "/admin/sso") and not user.is_admin:
        abort(403)

    return render_template("index.html", initial_page=request.path)
