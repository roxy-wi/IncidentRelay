from flask import Blueprint, jsonify, request

from app.notifiers.browser_push import service as browser_push
from app.services.validation import make_error_response, safe_exception_response

push_bp = Blueprint("push_api", __name__)


@push_bp.route("/profile/push/vapid-public-key", methods=["GET"])
def get_vapid_public_key():
    """Return public VAPID key for PushManager.subscribe()."""
    return jsonify(browser_push.get_public_config())


@push_bp.route("/profile/push/subscriptions", methods=["GET"])
def list_subscriptions():
    """Return current user's browser push devices."""
    return jsonify(
        browser_push.list_user_subscriptions(request.current_user)
    )


@push_bp.route("/profile/push/subscriptions", methods=["POST"])
def save_subscription():
    """Create or update current browser push subscription."""
    payload = request.json or {}

    try:
        subscription = browser_push.save_user_subscription(
            request.current_user,
            endpoint=payload.get("endpoint"),
            keys=payload.get("keys") or {},
            device_name=payload.get("device_name"),
            user_agent=payload.get("user_agent") or request.headers.get("User-Agent"),
        )
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="validation_error",
            message="Invalid browser push subscription request.",
            status_code=400,
        )

    return jsonify(browser_push.serialize_subscription(subscription)), 201


@push_bp.route("/profile/push/subscriptions/<int:subscription_id>", methods=["DELETE"])
def disable_subscription(subscription_id):
    """Disable one browser push device."""
    subscription = browser_push.disable_user_subscription(
        request.current_user,
        subscription_id,
    )

    if not subscription:
        return make_error_response(
            error="not_found",
            message="Push subscription was not found.",
            status_code=404,
        )

    return jsonify({"disabled": True, "id": subscription_id})


@push_bp.route("/profile/push/test", methods=["POST"])
def send_test_push():
    """Send test push to current user's devices."""
    count = browser_push.send_test_push(request.current_user)

    return jsonify({"status": "sent", "sent": count})


@push_bp.route("/push/actions", methods=["POST"])
def run_push_action():
    """Execute ACK/Resolve from notification action token."""
    payload = request.json or {}

    result = browser_push.execute_push_action(
        token=payload.get("token"),
        action=payload.get("action"),
    )

    status = 200 if result.get("ok") else 400
    return jsonify(result), status
