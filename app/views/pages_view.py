import json
from pathlib import Path
from urllib.parse import quote

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

from app.i18n import get_current_locale, translate
from app.login import normalize_auth_redirect_target
from app.middleware import load_jwt_user


pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/manifest.webmanifest")
def pwa_manifest():
    """Serve a locale-aware PWA manifest with the correct content type."""
    manifest_path = Path(current_app.static_folder) / "manifest.webmanifest"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    locale = get_current_locale()

    payload["lang"] = locale
    payload["description"] = translate("pwa.manifest.description")

    shortcut_keys = ("alerts", "calendar", "services")
    for shortcut, shortcut_key in zip(
        payload.get("shortcuts", []),
        shortcut_keys,
    ):
        shortcut["name"] = translate(f"pwa.shortcut.{shortcut_key}.name")
        shortcut["short_name"] = translate(
            f"pwa.shortcut.{shortcut_key}.short_name"
        )
        shortcut["description"] = translate(
            f"pwa.shortcut.{shortcut_key}.description"
        )

    screenshot_keys = ("desktop", "mobile")
    for screenshot, screenshot_key in zip(
        payload.get("screenshots", []),
        screenshot_keys,
    ):
        screenshot["label"] = translate(
            f"pwa.screenshot.{screenshot_key}"
        )

    response = make_response(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )
    response.mimetype = "application/manifest+json"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Vary"] = "Cookie, Accept-Language"
    return response


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
@pages_bp.route("/business-services")
@pages_bp.route("/business-services/")
@pages_bp.route("/heartbeats")
@pages_bp.route("/heartbeats/")
@pages_bp.route("/maintenance-windows")
@pages_bp.route("/maintenance-windows/")
@pages_bp.route("/event-orchestration")
@pages_bp.route("/event-orchestration/")
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
            return redirect(normalize_auth_redirect_target(request.args.get("next")))
        return render_template("login_only.html")

    if not user:
        target = normalize_auth_redirect_target(request.full_path.rstrip("?"))
        return redirect(f"/login?next={quote(target, safe='')}")

    if request.path in ("/admin/users", "/groups", "/admin/sso") and not user.is_admin:
        abort(403)

    return render_template("index.html", initial_page=request.path)
