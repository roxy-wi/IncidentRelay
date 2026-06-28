from flask import Blueprint, jsonify, request

from app.api.schemas.notification_policies import (
    NotificationPolicyCreateSchema,
    NotificationPolicyRuleCreateSchema,
    NotificationPolicyRuleOrderSchema,
    NotificationPolicyRuleUpdateSchema,
    NotificationPolicyUpdateSchema,
)
from app.services.audit import write_audit
from app.services.notifications.policies import service as policy_service
from app.services.rbac import (
    current_user,
    get_allowed_team_ids,
    require_team_read,
    require_team_write,
)
from app.services.validation import validate_body
from app.services.service_catalog.reconciliation import reconcile_notification_policy_services

notification_policies_bp = Blueprint("notification_policies_api", __name__)


@notification_policies_bp.errorhandler(policy_service.NotificationPolicyError)
def handle_notification_policy_error(error):
    """Convert notification policy domain errors to API responses."""
    if isinstance(error, policy_service.NotificationPolicyNotFoundError):
        error_code = "notification_policy_not_found"
        status = 404
    elif isinstance(error, policy_service.NotificationPolicyInUseError):
        error_code = "notification_policy_in_use"
        status = 409
    elif isinstance(error, policy_service.NotificationPolicyConflictError):
        error_code = "notification_policy_conflict"
        status = 409
    else:
        error_code = "notification_policy_invalid"
        status = 400

    return jsonify({
        "error": error_code,
        "message": str(error),
    }), status


def _require_policy_read(policy_id):
    policy = policy_service.get_policy(policy_id)
    error = require_team_read(policy.team_id)

    if error:
        return None, error

    return policy, None


def _require_policy_write(policy_id):
    policy = policy_service.get_policy(policy_id)
    error = require_team_write(policy.team_id)

    if error:
        return None, error

    return policy, None


def _require_policy_rule_write(policy_id, rule_id):
    policy, error = _require_policy_write(policy_id)

    if error:
        return None, None, error

    rule = policy_service.get_rule(rule_id)

    if rule.policy_id != policy.id:
        raise policy_service.NotificationPolicyNotFoundError(
            "notification policy rule was not found"
        )

    return policy, rule, None


@notification_policies_bp.route("", methods=["GET"])
def list_notification_policies():
    """Return notification policies visible to the current user."""
    team_id = request.args.get("team_id", type=int)
    enabled_only = request.args.get("enabled_only") == "1"

    if team_id:
        error = require_team_read(team_id)

        if error:
            return error

        team_ids = None
    else:
        team_ids = get_allowed_team_ids()

    policies = policy_service.list_policies(
        team_id=team_id,
        team_ids=team_ids,
        enabled_only=enabled_only,
        current_user=current_user(),
    )

    return jsonify(policies)


@notification_policies_bp.route("/<int:policy_id>", methods=["GET"])
def get_notification_policy(policy_id):
    """Return one notification policy with its rules."""
    policy, error = _require_policy_read(policy_id)

    if error:
        return error

    return jsonify(
        policy_service.serialize_policy(
            policy,
            current_user(),
            include_rules=True,
        )
    )


@notification_policies_bp.route("", methods=["POST"])
def create_notification_policy():
    """Create or restore a notification policy."""
    payload, error = validate_body(NotificationPolicyCreateSchema)

    if error:
        return error

    error = require_team_write(payload.team_id)

    if error:
        return error

    policy = policy_service.create_policy(payload)

    write_audit(
        "notification_policy.create",
        object_type="notification_policy",
        object_id=policy.id,
        group_id=policy.team.group_id,
        team_id=policy.team_id,
        data=payload.model_dump(),
    )

    return jsonify(policy_service.serialize_policy(policy, current_user())), 201


@notification_policies_bp.route("/<int:policy_id>", methods=["PUT"])
def update_notification_policy(policy_id):
    """Update a notification policy."""
    policy_before, error = _require_policy_write(policy_id)

    if error:
        return error

    payload, error = validate_body(NotificationPolicyUpdateSchema)

    if error:
        return error

    policy = policy_service.update_policy(policy_before.id, payload)

    write_audit(
        "notification_policy.update",
        object_type="notification_policy",
        object_id=policy.id,
        group_id=policy.team.group_id,
        team_id=policy.team_id,
        data=payload.model_dump(exclude_unset=True),
    )

    reconcile_notification_policy_services(
        policy.id,
        trigger="notification_policy_updated",
        actor_user=current_user(),
    )

    return jsonify(policy_service.serialize_policy(policy, current_user())), 201


@notification_policies_bp.route("/<int:policy_id>", methods=["DELETE"])
def delete_notification_policy(policy_id):
    """Soft-delete a notification policy."""
    policy_before, error = _require_policy_write(policy_id)

    if error:
        return error

    policy = policy_service.delete_policy(policy_before.id)

    write_audit(
        "notification_policy.delete",
        object_type="notification_policy",
        object_id=policy.id,
        group_id=policy.team.group_id,
        team_id=policy.team_id,
        data={"deleted": True},
    )

    reconcile_notification_policy_services(
        policy.id,
        trigger="notification_policy_deleted",
        actor_user=current_user(),
    )

    return jsonify({
        "deleted": True,
        "id": policy.id,
    })


@notification_policies_bp.route("/<int:policy_id>/rules", methods=["POST"])
def create_notification_policy_rule(policy_id):
    """Create a notification policy rule."""
    policy, error = _require_policy_write(policy_id)

    if error:
        return error

    payload, error = validate_body(NotificationPolicyRuleCreateSchema)

    if error:
        return error

    rule = policy_service.create_rule(policy.id, payload)

    write_audit(
        "notification_policy_rule.create",
        object_type="notification_policy_rule",
        object_id=rule.id,
        group_id=policy.team.group_id,
        team_id=policy.team_id,
        data=payload.model_dump(),
    )

    reconcile_notification_policy_services(
        policy.id,
        trigger="notification_policy_rule_created",
        actor_user=current_user(),
    )

    return jsonify(policy_service.serialize_rule(rule)), 201


@notification_policies_bp.route("/<int:policy_id>/rules/<int:rule_id>", methods=["PUT"])
def update_notification_policy_rule(policy_id, rule_id):
    """Update a notification policy rule."""
    policy, rule_before, error = _require_policy_rule_write(policy_id, rule_id)

    if error:
        return error

    payload, error = validate_body(NotificationPolicyRuleUpdateSchema)

    if error:
        return error

    rule = policy_service.update_rule(rule_before.id, payload)

    write_audit(
        "notification_policy_rule.update",
        object_type="notification_policy_rule",
        object_id=rule.id,
        group_id=policy.team.group_id,
        team_id=policy.team_id,
        data=payload.model_dump(exclude_unset=True),
    )

    reconcile_notification_policy_services(
        policy.id,
        trigger="notification_policy_rule_created",
        actor_user=current_user(),
    )

    return jsonify(policy_service.serialize_rule(rule))


@notification_policies_bp.route("/<int:policy_id>/rules/<int:rule_id>", methods=["DELETE"])
def delete_notification_policy_rule(policy_id, rule_id):
    """Soft-delete a notification policy rule."""
    policy, rule_before, error = _require_policy_rule_write(policy_id, rule_id)

    if error:
        return error

    rule = policy_service.delete_rule(rule_before.id)

    write_audit(
        "notification_policy_rule.delete",
        object_type="notification_policy_rule",
        object_id=rule.id,
        group_id=policy.team.group_id,
        team_id=policy.team_id,
        data={"deleted": True},
    )

    reconcile_notification_policy_services(
        policy.id,
        trigger="notification_policy_rule_created",
        actor_user=current_user(),
    )

    return jsonify({
        "deleted": True,
        "id": rule.id,
    })


@notification_policies_bp.route("/<int:policy_id>/rules/order", methods=["PUT"])
def reorder_notification_policy_rules(policy_id):
    """Replace the complete notification policy rule order."""
    policy, error = _require_policy_write(policy_id)

    if error:
        return error

    payload, error = validate_body(NotificationPolicyRuleOrderSchema)

    if error:
        return error

    rules = policy_service.reorder_rules(policy.id, payload.rule_ids)

    write_audit(
        "notification_policy_rule.reorder",
        object_type="notification_policy",
        object_id=policy.id,
        group_id=policy.team.group_id,
        team_id=policy.team_id,
        data={"rule_ids": payload.rule_ids},
    )

    return jsonify([
        policy_service.serialize_rule(rule)
        for rule in rules
    ])
