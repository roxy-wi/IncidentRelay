from flask import Blueprint, jsonify, request

from app.api.schemas.priority_policies import (
    PriorityPolicyCreateSchema,
    PriorityPolicyRuleCreateSchema,
    PriorityPolicyRuleReorderSchema,
    PriorityPolicyRuleUpdateSchema,
    PriorityPolicyUpdateSchema,
)
from app.services.audit import write_audit
from app.services.incidents.priority_policies import service
from app.services.rbac import current_user, get_allowed_team_ids, require_team_read, require_team_write
from app.services.validation import validate_body


priority_policies_bp = Blueprint("priority_policies_api", __name__)


@priority_policies_bp.errorhandler(service.PriorityPolicyError)
def handle_priority_policy_error(error):
    """Convert priority policy domain errors to API responses."""
    if isinstance(error, service.PriorityPolicyNotFoundError):
        error_code = "priority_policy_not_found"
        status = 404
    elif isinstance(error, service.PriorityPolicyInUseError):
        error_code = "priority_policy_in_use"
        status = 409
    elif isinstance(error, service.PriorityPolicyConflictError):
        error_code = "priority_policy_conflict"
        status = 409
    else:
        error_code = "priority_policy_invalid"
        status = 400

    return jsonify({"error": error_code, "message": str(error)}), status


def _require_policy_read(policy_id):
    policy = service.get_policy(policy_id)
    error = require_team_read(policy.team_id)

    if error:
        return None, error

    return policy, None


def _require_policy_write(policy_id):
    policy = service.get_policy(policy_id)
    error = require_team_write(policy.team_id)

    if error:
        return None, error

    return policy, None


def _require_rule_write(policy_id, rule_id):
    policy, error = _require_policy_write(policy_id)

    if error:
        return None, None, error

    rule = service.get_rule(rule_id)

    if rule.policy_id != policy.id:
        raise service.PriorityPolicyNotFoundError("priority policy rule was not found")

    return policy, rule, None


@priority_policies_bp.route("", methods=["GET"])
def list_priority_policies():
    """Return priority policies visible to the current user."""
    team_id = request.args.get("team_id", type=int)
    enabled_only = request.args.get("enabled_only") == "1"

    if team_id:
        error = require_team_read(team_id)

        if error:
            return error

        team_ids = None
    else:
        team_ids = get_allowed_team_ids()

    policies = service.list_policies(team_id=team_id, team_ids=team_ids, enabled_only=enabled_only, current_user=current_user())
    return jsonify(policies)


@priority_policies_bp.route("/<int:policy_id>", methods=["GET"])
def get_priority_policy(policy_id):
    """Return one priority policy with rules."""
    policy, error = _require_policy_read(policy_id)

    if error:
        return error

    return jsonify(service.serialize_policy(policy, current_user(), include_rules=True))


@priority_policies_bp.route("", methods=["POST"])
def create_priority_policy():
    """Create or restore a priority policy."""
    payload, error = validate_body(PriorityPolicyCreateSchema)

    if error:
        return error

    error = require_team_write(payload.team_id)

    if error:
        return error

    policy = service.create_policy(payload)

    write_audit(
        "priority_policy.create",
        object_type="priority_policy",
        object_id=policy.id,
        group_id=policy.team.group_id,
        team_id=policy.team_id,
        data=payload.model_dump(),
    )

    return jsonify(service.serialize_policy(policy, current_user())), 201


@priority_policies_bp.route("/<int:policy_id>", methods=["PUT"])
def update_priority_policy(policy_id):
    """Update a priority policy."""
    policy_before, error = _require_policy_write(policy_id)

    if error:
        return error

    payload, error = validate_body(PriorityPolicyUpdateSchema)

    if error:
        return error

    policy = service.update_policy(policy_before.id, payload)

    write_audit(
        "priority_policy.update",
        object_type="priority_policy",
        object_id=policy.id,
        group_id=policy.team.group_id,
        team_id=policy.team_id,
        data=payload.model_dump(exclude_unset=True),
    )

    return jsonify(service.serialize_policy(policy, current_user(), include_rules=True))


@priority_policies_bp.route("/<int:policy_id>", methods=["DELETE"])
def delete_priority_policy(policy_id):
    """Soft-delete a priority policy."""
    policy_before, error = _require_policy_write(policy_id)

    if error:
        return error

    policy = service.delete_policy(policy_before.id)

    write_audit(
        "priority_policy.delete",
        object_type="priority_policy",
        object_id=policy.id,
        group_id=policy.team.group_id,
        team_id=policy.team_id,
        data={"deleted": True},
    )

    return jsonify({"deleted": True, "id": policy.id})


@priority_policies_bp.route("/<int:policy_id>/rules", methods=["POST"])
def create_priority_policy_rule(policy_id):
    """Create a priority policy rule."""
    policy, error = _require_policy_write(policy_id)

    if error:
        return error

    payload, error = validate_body(PriorityPolicyRuleCreateSchema)

    if error:
        return error

    rule = service.create_rule(policy.id, payload)

    write_audit(
        "priority_policy_rule.create",
        object_type="priority_policy_rule",
        object_id=rule.id,
        group_id=policy.team.group_id,
        team_id=policy.team_id,
        data=payload.model_dump(),
    )

    return jsonify(service.serialize_rule(rule)), 201


@priority_policies_bp.route("/<int:policy_id>/rules/<int:rule_id>", methods=["PUT"])
def update_priority_policy_rule(policy_id, rule_id):
    """Update a priority policy rule."""
    policy, rule_before, error = _require_rule_write(policy_id, rule_id)

    if error:
        return error

    payload, error = validate_body(PriorityPolicyRuleUpdateSchema)

    if error:
        return error

    rule = service.update_rule(rule_before.id, payload)

    write_audit(
        "priority_policy_rule.update",
        object_type="priority_policy_rule",
        object_id=rule.id,
        group_id=policy.team.group_id,
        team_id=policy.team_id,
        data=payload.model_dump(exclude_unset=True),
    )

    return jsonify(service.serialize_rule(rule))


@priority_policies_bp.route("/<int:policy_id>/rules/<int:rule_id>", methods=["DELETE"])
def delete_priority_policy_rule(policy_id, rule_id):
    """Soft-delete a priority policy rule."""
    policy, rule_before, error = _require_rule_write(policy_id, rule_id)

    if error:
        return error

    rule = service.delete_rule(rule_before.id)

    write_audit(
        "priority_policy_rule.delete",
        object_type="priority_policy_rule",
        object_id=rule.id,
        group_id=policy.team.group_id,
        team_id=policy.team_id,
        data={"deleted": True},
    )

    return jsonify({"deleted": True, "id": rule.id})


@priority_policies_bp.route("/<int:policy_id>/rules/reorder", methods=["PUT"])
def reorder_priority_policy_rules(policy_id):
    """Replace the complete priority policy rule order."""
    policy, error = _require_policy_write(policy_id)

    if error:
        return error

    payload, error = validate_body(PriorityPolicyRuleReorderSchema)

    if error:
        return error

    rules = service.reorder_rules(policy.id, payload.rule_ids)

    write_audit(
        "priority_policy_rule.reorder",
        object_type="priority_policy",
        object_id=policy.id,
        group_id=policy.team.group_id,
        team_id=policy.team_id,
        data={"rule_ids": payload.rule_ids},
    )

    return jsonify([service.serialize_rule(rule) for rule in rules])
