from flask import Blueprint, jsonify, request

from app.services.rbac import current_user
from app.api.schemas.escalation_policies import (
    EscalationPolicyCreateSchema,
    EscalationPolicyRuleSchema,
    EscalationPolicyRuleUpdateSchema,
    EscalationPolicyUpdateSchema,
)
from app.modules.db import escalation_policies_repo
from app.services import escalation_policies as escalation_policy_service
from app.services.audit import write_audit
from app.services.rbac import get_allowed_team_ids, require_team_read, require_team_write
from app.services.validation import (
    make_error_response,
    safe_exception_response,
    validate_body,
)
from app.services.service_catalog.reconciliation import reconcile_escalation_policy_services

escalation_policies_bp = Blueprint("escalation_policies_api", __name__)


def _validate_rule_target_values(policy, target_type, target_id):
    """Ensure rule target exists and belongs to the same team as the policy."""
    if target_type == "rotation":
        if not escalation_policies_repo.rotation_belongs_to_team(target_id, policy.team.id):
            return make_error_response(
                "rotation_team_mismatch",
                "Rotation does not belong to policy team",
                400,
                rotation_id=target_id,
                team_id=policy.team.id,
            )

    if target_type == "user":
        if not escalation_policies_repo.user_belongs_to_team(target_id, policy.team.id):
            return make_error_response(
                "user_team_mismatch",
                "User is not an active member of policy team",
                400,
                user_id=target_id,
                team_id=policy.team.id,
            )

    return None


def _validate_rule_target(policy, payload):
    """Validate create payload target."""
    return _validate_rule_target_values(policy, payload.target_type, payload.target_id)


def _validate_rule_update_target(policy, rule, payload):
    """Validate update payload target using current rule values as fallback."""
    if payload.target_type is None and payload.target_id is None:
        return None

    target_type = payload.target_type or rule.target_type

    if payload.target_id is not None:
        target_id = payload.target_id
    elif target_type == "rotation" and rule.target_rotation:
        target_id = rule.target_rotation.id
    elif target_type == "user" and rule.target_user:
        target_id = rule.target_user.id
    else:
        return make_error_response(
            "rule_target_required",
            "target_id is required for this rule target",
            400,
        )

    return _validate_rule_target_values(policy, target_type, target_id)


@escalation_policies_bp.route("", methods=["GET"])
def list_escalation_policies():
    """Return escalation policies visible to current user."""
    team_id = request.args.get("team_id", type=int)

    if team_id:
        error = require_team_read(team_id)
        if error:
            return error
        policies = escalation_policies_repo.list_policies(team_id=team_id)
    else:
        policies = escalation_policies_repo.list_policies(team_ids=get_allowed_team_ids())

    return jsonify([
        escalation_policy_service.serialize_policy(policy, include_rules=True, request_user=current_user())
        for policy in policies
    ])


@escalation_policies_bp.route("/<int:policy_id>", methods=["GET"])
def get_escalation_policy(policy_id):
    """Return one escalation policy."""
    policy = escalation_policies_repo.get_policy(policy_id)

    error = require_team_read(policy.team.id)
    if error:
        return error

    return jsonify(escalation_policy_service.serialize_policy(policy, include_rules=True, request_user=current_user()))


@escalation_policies_bp.route("", methods=["POST"])
def create_escalation_policy():
    """Create an escalation policy."""
    payload, error = validate_body(EscalationPolicyCreateSchema)
    if error:
        return error

    error = require_team_write(payload.team_id)
    if error:
        return error

    policy = escalation_policies_repo.create_policy(
        team_id=payload.team_id,
        name=payload.name,
        description=payload.description,
        enabled=payload.enabled,
        repeat_count=payload.repeat_count,
    )

    write_audit(
        "escalation_policy.create",
        object_type="escalation_policy",
        object_id=policy.id,
        team_id=policy.team.id,
        data=payload.model_dump(),
    )

    return jsonify(escalation_policy_service.serialize_policy(policy, include_rules=True, request_user=current_user())), 201


@escalation_policies_bp.route("/<int:policy_id>", methods=["PUT"])
def update_escalation_policy(policy_id):
    """Update an escalation policy."""
    payload, error = validate_body(EscalationPolicyUpdateSchema)
    if error:
        return error

    policy_before = escalation_policies_repo.get_policy(policy_id)

    error = require_team_write(policy_before.team.id)
    if error:
        return error

    policy = escalation_policies_repo.update_policy(
        policy_id,
        payload.model_dump(exclude_unset=True),
    )

    write_audit(
        "escalation_policy.update",
        object_type="escalation_policy",
        object_id=policy.id,
        team_id=policy.team.id,
        data=payload.model_dump(exclude_unset=True),
    )

    reconcile_escalation_policy_services(
        policy.id,
        trigger="escalation_policy_updated",
        actor_user=current_user(),
    )

    return jsonify(escalation_policy_service.serialize_policy(policy, include_rules=True, request_user=current_user()))


@escalation_policies_bp.route("/<int:policy_id>", methods=["DELETE"])
def delete_escalation_policy(policy_id):
    """Disable and soft-delete an escalation policy."""
    policy_before = escalation_policies_repo.get_policy(policy_id)

    error = require_team_write(policy_before.team.id)
    if error:
        return error

    policy = escalation_policies_repo.soft_delete_policy(policy_id)

    write_audit(
        "escalation_policy.delete",
        object_type="escalation_policy",
        object_id=policy.id,
        team_id=policy.team.id,
        data={"deleted": True},
    )

    reconcile_escalation_policy_services(
        policy.id,
        trigger="escalation_policy_deleted",
        actor_user=current_user(),
    )

    return jsonify({"deleted": True, "id": policy.id, "name": policy.name})


@escalation_policies_bp.route("/<int:policy_id>/rules", methods=["GET"])
def list_escalation_policy_rules(policy_id):
    """Return policy rules."""
    policy = escalation_policies_repo.get_policy(policy_id)

    error = require_team_read(policy.team.id)
    if error:
        return error

    return jsonify([
        escalation_policy_service.serialize_rule(rule)
        for rule in escalation_policies_repo.list_rules(policy.id)
    ])


@escalation_policies_bp.route("/<int:policy_id>/rules", methods=["POST"])
def create_escalation_policy_rule(policy_id):
    """Create a policy rule."""
    payload, error = validate_body(EscalationPolicyRuleSchema)
    if error:
        return error

    policy = escalation_policies_repo.get_policy(policy_id)

    error = require_team_write(policy.team.id)
    if error:
        return error

    target_error = _validate_rule_target(policy, payload)
    if target_error:
        return target_error

    try:
        rule = escalation_policies_repo.create_rule(policy.id, **payload.model_dump())
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="rule_conflict",
            message="Escalation policy rule conflicts with an existing rule.",
            status_code=409,
        )

    write_audit(
        "escalation_policy_rule.create",
        object_type="escalation_policy_rule",
        object_id=rule.id,
        team_id=policy.team.id,
        data=payload.model_dump(),
    )

    reconcile_escalation_policy_services(
        policy.id,
        trigger="escalation_policy_rule_created",
        actor_user=current_user(),
    )

    return jsonify(escalation_policy_service.serialize_rule(rule)), 201


@escalation_policies_bp.route("/rules/<int:rule_id>", methods=["PUT"])
def update_escalation_policy_rule(rule_id):
    """Update a policy rule."""
    payload, error = validate_body(EscalationPolicyRuleUpdateSchema)
    if error:
        return error

    rule_before = escalation_policies_repo.get_rule(rule_id)
    policy = rule_before.policy

    error = require_team_write(policy.team.id)
    if error:
        return error

    target_error = _validate_rule_update_target(policy, rule_before, payload)
    if target_error:
        return target_error

    try:
        rule = escalation_policies_repo.update_rule(
            rule_id,
            payload.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="rule_validation_failed",
            message="Invalid escalation policy rule request.",
            status_code=400,
        )

    write_audit(
        "escalation_policy_rule.update",
        object_type="escalation_policy_rule",
        object_id=rule.id,
        team_id=policy.team.id,
        data=payload.model_dump(exclude_unset=True),
    )

    reconcile_escalation_policy_services(
        policy.id,
        trigger="escalation_policy_rule_created",
        actor_user=current_user(),
    )

    return jsonify(escalation_policy_service.serialize_rule(rule))


@escalation_policies_bp.route("/rules/<int:rule_id>", methods=["DELETE"])
def delete_escalation_policy_rule(rule_id):
    """Delete a policy rule."""
    rule = escalation_policies_repo.get_rule(rule_id)
    policy = rule.policy

    error = require_team_write(policy.team.id)
    if error:
        return error

    escalation_policies_repo.delete_rule(rule_id)

    write_audit(
        "escalation_policy_rule.delete",
        object_type="escalation_policy_rule",
        object_id=rule_id,
        team_id=policy.team.id,
        data={"deleted": True},
    )

    reconcile_escalation_policy_services(
        policy.id,
        trigger="escalation_policy_rule_created",
        actor_user=current_user(),
    )

    return jsonify({"deleted": True, "id": rule_id})
