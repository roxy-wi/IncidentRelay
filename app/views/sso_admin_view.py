from flask import Blueprint, jsonify, request
from peewee import IntegrityError

from app.api.schemas.sso import (
    SsoGroupMappingCreateSchema,
    SsoGroupMappingUpdateSchema,
    SsoProviderCreateSchema,
    SsoProviderUpdateSchema,
)
from app.modules.db.common import integrity_conflict, unique_field_conflict
from app.modules.db import sso_repo
from app.services.audit import write_audit
from app.services.rbac import require_admin_user
from app.services.serializers import serialize_sso_group_mapping, serialize_sso_provider
from app.services.validation import validate_body
from app.api.schemas.sso import SsoSamlMetadataParseRequest
from app.modules.sso.saml_metadata import SamlMetadataError, parse_saml_idp_metadata


sso_admin_bp = Blueprint("sso_admin_api", __name__)


def _safe_provider_payload(data):
    """Return provider payload safe for audit logs."""
    result = dict(data)
    if "client_secret" in result:
        result["client_secret"] = "***" if result["client_secret"] else None
    if "saml_sp_private_key" in result:
        result["saml_sp_private_key"] = "***" if result["saml_sp_private_key"] else None
    return result


@sso_admin_bp.route("/providers", methods=["GET"])
def list_providers():
    """Return all SSO providers."""
    error = require_admin_user()
    if error:
        return error

    providers = sso_repo.list_providers(include_disabled=True)
    return jsonify([serialize_sso_provider(provider) for provider in providers])


@sso_admin_bp.route("/providers", methods=["POST"])
def create_provider():
    """Create SSO provider."""
    error = require_admin_user()
    if error:
        return error

    payload, error = validate_body(SsoProviderCreateSchema)
    if error:
        return error

    data = payload.model_dump()

    try:
        provider = sso_repo.create_provider(data)
    except IntegrityError as exc:
        error_text = str(exc).lower()
        if "slug" in error_text:
            return unique_field_conflict(
                "slug",
                data.get("slug"),
                "SSO provider with this slug already exists",
            )
        return integrity_conflict("SSO provider could not be saved because it conflicts with existing data")

    write_audit(
        "sso.provider.create",
        object_type="sso_provider",
        object_id=provider.id,
        data=_safe_provider_payload(data),
    )

    return jsonify(serialize_sso_provider(provider)), 201


@sso_admin_bp.route("/providers/<int:provider_id>", methods=["PUT"])
def update_provider(provider_id):
    """Update SSO provider."""
    error = require_admin_user()
    if error:
        return error

    payload, error = validate_body(SsoProviderUpdateSchema)
    if error:
        return error

    data = payload.model_dump(exclude_unset=True)

    try:
        provider = sso_repo.update_provider(provider_id, data)
    except IntegrityError as exc:
        error_text = str(exc).lower()
        if "slug" in error_text:
            return unique_field_conflict(
                "slug",
                data.get("slug"),
                "SSO provider with this slug already exists",
            )
        return integrity_conflict("SSO provider could not be saved because it conflicts with existing data")

    write_audit(
        "sso.provider.update",
        object_type="sso_provider",
        object_id=provider.id,
        data=_safe_provider_payload(data),
    )

    return jsonify(serialize_sso_provider(provider))


@sso_admin_bp.route("/providers/<int:provider_id>", methods=["DELETE"])
def delete_provider(provider_id):
    """Soft-delete SSO provider."""
    error = require_admin_user()
    if error:
        return error

    provider = sso_repo.soft_delete_provider(provider_id)

    write_audit(
        "sso.provider.delete",
        object_type="sso_provider",
        object_id=provider.id,
        data={
            "slug": provider.slug,
            "label": provider.label,
            "deleted": True,
        },
    )

    return jsonify({
        "deleted": True,
        "id": provider.id,
        "slug": provider.slug,
        "label": provider.label,
    })


@sso_admin_bp.route("/providers/<int:provider_id>/mappings", methods=["GET"])
def list_group_mappings(provider_id):
    """Return group mappings for provider."""
    error = require_admin_user()
    if error:
        return error

    mappings = sso_repo.list_group_mappings(provider_id)
    return jsonify([serialize_sso_group_mapping(mapping) for mapping in mappings])


@sso_admin_bp.route("/providers/<int:provider_id>/mappings", methods=["POST"])
def create_group_mapping(provider_id):
    """Create group mapping for provider."""
    error = require_admin_user()
    if error:
        return error

    payload, error = validate_body(SsoGroupMappingCreateSchema)
    if error:
        return error

    data = payload.model_dump()

    try:
        mapping = sso_repo.create_group_mapping(provider_id, data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except IntegrityError:
        return integrity_conflict("SSO group mapping could not be saved because it conflicts with existing data")

    write_audit(
        "sso.group_mapping.create",
        object_type="sso_group_mapping",
        object_id=mapping.id,
        group_id=mapping.incidentrelay_group.id,
        data={
            "provider_id": provider_id,
            **data,
        },
    )

    return jsonify(serialize_sso_group_mapping(mapping)), 201


@sso_admin_bp.route("/mappings/<int:mapping_id>", methods=["PUT"])
def update_group_mapping(mapping_id):
    """Update group mapping."""
    error = require_admin_user()
    if error:
        return error

    payload, error = validate_body(SsoGroupMappingUpdateSchema)
    if error:
        return error

    data = payload.model_dump()

    try:
        mapping = sso_repo.update_group_mapping(mapping_id, data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except IntegrityError:
        return integrity_conflict("SSO group mapping could not be saved because it conflicts with existing data")

    write_audit(
        "sso.group_mapping.update",
        object_type="sso_group_mapping",
        object_id=mapping.id,
        group_id=mapping.incidentrelay_group.id,
        data=data,
    )

    return jsonify(serialize_sso_group_mapping(mapping))


@sso_admin_bp.route("/mappings/<int:mapping_id>", methods=["DELETE"])
def delete_group_mapping(mapping_id):
    """Delete group mapping."""
    error = require_admin_user()
    if error:
        return error

    mapping = sso_repo.get_group_mapping(mapping_id)
    group_id = mapping.incidentrelay_group.id
    provider_id = mapping.provider.id

    sso_repo.delete_group_mapping(mapping_id)

    write_audit(
        "sso.group_mapping.delete",
        object_type="sso_group_mapping",
        object_id=mapping_id,
        group_id=group_id,
        data={
            "provider_id": provider_id,
            "mapping_id": mapping_id,
            "deleted": True,
        },
    )

    return jsonify({
        "deleted": True,
        "id": mapping_id,
    })


@sso_admin_bp.route("/saml/metadata/parse", methods=["POST"])
def parse_saml_metadata():
    """
    Parse SAML IdP metadata and return fields for the provider form.
    """
    require_admin_user()

    try:
        payload = SsoSamlMetadataParseRequest.model_validate(
            request.get_json(silent=True) or {}
        )
        metadata = parse_saml_idp_metadata(payload.metadata_url)
        return jsonify(metadata)
    except SamlMetadataError as exc:
        return jsonify(
            {
                "error": exc.code,
                "message": exc.message,
            }
        ), exc.status_code
