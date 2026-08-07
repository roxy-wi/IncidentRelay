from pathlib import Path

from app.modules.db.models import SsoGroupMapping, SsoProvider
from app.views.sso_admin_view import update_group_mapping
from tests.factories import create_group, create_user, unique


SSO_SCRIPT = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "pages" / "sso.js"


def _make_oidc_provider() -> SsoProvider:
    return SsoProvider.create(
        slug=unique("oidc-edit"),
        label="Editable OIDC",
        protocol="oidc",
        enabled=True,
        client_id="incidentrelay",
        oidc_metadata_url="https://idp.example.com/.well-known/openid-configuration",
        oidc_issuer="https://idp.example.com",
        oidc_jwks_uri="https://idp.example.com/jwks",
        oidc_scope="openid email profile",
        subject_claim="sub",
        email_claim="email",
        username_claim="preferred_username",
        display_name_claim="name",
        groups_claim="groups",
    )


def test_sso_mapping_edit_form_uses_role_values() -> None:
    """The edit modal must assign select values, not call a generated method name."""
    script = SSO_SCRIPT.read_text(encoding="utf-8")
    function_start = script.index("function openExistingSsoMappingModal(mapping)")
    function_end = script.index("\nfunction resetSsoMappingForm()", function_start)
    function_body = script[function_start:function_end]

    assert ".valssoRoleLabel" not in function_body
    assert '$("#sso-mapping-role").val(mapping.group_role || "viewer");' in function_body
    assert '$("#sso-mapping-team-role").val(mapping.team_role || "viewer");' in function_body
    assert '$("#sso-mapping-priority").val(mapping.priority ?? 100);' in function_body


def test_admin_can_update_oidc_mapping_rule(app) -> None:
    admin = create_user(username=unique("oidc-edit-admin"), is_admin=True)
    provider = _make_oidc_provider()
    original_group = create_group(slug=unique("original"), name="Original")
    replacement_group = create_group(slug=unique("replacement"), name="Replacement")
    mapping = SsoGroupMapping.create(
        provider=provider,
        external_group="old-external-group",
        incidentrelay_group=original_group,
        group_role="viewer",
        active=True,
        priority=100,
    )

    with app.test_request_context(
        f"/api/admin/sso/mappings/{mapping.id}",
        method="PUT",
        json={
            "external_group": "new-external-group",
            "group_id": replacement_group.id,
            "group_role": "editor",
            "team_id": None,
            "team_role": None,
            "active": False,
            "priority": 20,
        },
    ):
        from flask import request

        request.current_user = admin
        response = update_group_mapping(mapping.id)

    data = response.get_json()
    updated = SsoGroupMapping.get_by_id(mapping.id)

    assert data["external_group"] == "new-external-group"
    assert data["group_id"] == replacement_group.id
    assert data["group_role"] == "editor"
    assert data["active"] is False
    assert data["priority"] == 20
    assert updated.external_group == "new-external-group"
    assert updated.incidentrelay_group.id == replacement_group.id
    assert updated.group_role == "editor"
    assert updated.active is False
    assert updated.priority == 20
