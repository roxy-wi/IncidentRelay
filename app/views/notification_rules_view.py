from flask import Blueprint, jsonify, request

from app.api.schemas.notification_rules import (
    NotificationRuleCreateSchema,
    NotificationRuleUpdateSchema,
)
from app.services.notifications import rules
from app.services.validation import (
    safe_exception_response,
    validate_body,
)

notification_rules_bp = Blueprint("notification_rules_api", __name__)


@notification_rules_bp.route("/profile/notification-rules", methods=["GET"])
def list_profile_notification_rules():
    return jsonify(
        rules.list_user_rules(request.current_user)
    )


@notification_rules_bp.route("/profile/notification-rules", methods=["POST"])
def create_profile_notification_rule():
    data, error_response = validate_body(NotificationRuleCreateSchema)

    if error_response:
        return error_response

    try:
        rule = rules.create_user_rule(
            request.current_user,
            method=data.method,
            delay_seconds=data.delay_seconds,
            severities=data.severities,
            event_types=data.event_types,
            enabled=data.enabled,
        )
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="validation_error",
            message="Invalid notification rule request.",
            status_code=400,
        )

    return jsonify(rules.serialize_rule(rule)), 201


@notification_rules_bp.route("/profile/notification-rules/<int:rule_id>", methods=["PUT"])
def update_profile_notification_rule(rule_id):
    data, error_response = validate_body(NotificationRuleUpdateSchema)

    if error_response:
        return error_response

    try:
        rule = rules.update_user_rule(
            request.current_user,
            rule_id,
            data.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="validation_error",
            message="Invalid notification rule update request.",
            status_code=400,
        )

    return jsonify(rules.serialize_rule(rule))


@notification_rules_bp.route("/profile/notification-rules/<int:rule_id>", methods=["DELETE"])
def delete_profile_notification_rule(rule_id):
    try:
        rule = rules.delete_user_rule(
            request.current_user,
            rule_id,
        )
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="not_found",
            message="Notification rule not found.",
            status_code=404,
        )

    return jsonify(
        {
            "deleted": True,
            "id": rule.id,
        }
    )
