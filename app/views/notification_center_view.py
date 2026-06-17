from flask import Blueprint, jsonify, request

from app.services.notification_center import list_notification_center_items


notification_center_bp = Blueprint("notification_center_api", __name__)


def _request_user():
    return getattr(request, "current_user", None)


@notification_center_bp.route("", methods=["GET"])
def get_notification_center():
    limit = request.args.get("limit", 20, type=int)
    limit = max(1, min(limit, 100))

    return jsonify(
        list_notification_center_items(
            _request_user(),
            limit=limit,
        )
    )
