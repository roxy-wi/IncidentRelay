import json
import re
from datetime import datetime

from flask import make_response, redirect
from peewee import IntegrityError

from app.db import database_proxy as db
from app.login import create_access_token
from app.modules.db import groups_repo, teams_repo, users_repo
from app.modules.db.models import SsoGroupMapping, SsoIdentity, User, UserGroup
from app.settings import Config
from app.api.schemas.limits import normalize_phone


class SsoLoginError(Exception):
    """SSO login error safe to return to API clients."""

    def __init__(self, error, message, status_code=400):
        super().__init__(message)
        self.error = error
        self.message = message
        self.status_code = status_code


def build_sso_login_response(user, redirect_to="/"):
    """Issue IncidentRelay JWT cookie and redirect user to the UI."""
    token, _expires_at = create_access_token(user)

    response = make_response(redirect(redirect_to or "/"))
    response.set_cookie(
        Config.JWT_COOKIE_NAME,
        token,
        max_age=Config.JWT_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=Config.JWT_COOKIE_SECURE,
        samesite="Lax",
    )
    return response


def extract_claim(claims, claim_name, default=None):
    """Extract direct or dotted claim value."""
    if not claims or not claim_name:
        return default

    if claim_name in claims:
        return claims.get(claim_name)

    current = claims
    for part in str(claim_name).split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]

    return current


def normalize_sso_group_name(value):
    """Normalize external SSO group value for matching."""
    if value is None:
        return ""

    return str(value).strip().casefold()


def normalize_sso_group_set(values):
    """Normalize external SSO group claim values for matching."""
    return {
        normalize_sso_group_name(item)
        for item in normalize_groups(values)
        if normalize_sso_group_name(item)
    }


def ensure_user_active_group(user):
    """Ensure user's active_group points to one of active group memberships."""
    active_memberships = groups_repo.list_user_groups(user.id)
    active_group_ids = [membership.group.id for membership in active_memberships]

    if active_group_ids and user.active_group_id not in active_group_ids:
        user = users_repo.set_active_group(user.id, active_group_ids[0])

    return user, active_group_ids


def normalize_groups(value):
    """Normalize SSO group claim to a list of strings."""
    if value in (None, ""):
        return []

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []

        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
                return normalize_groups(parsed)
            except json.JSONDecodeError:
                pass

        return [item.strip() for item in stripped.split(",") if item.strip()]

    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            if item in (None, ""):
                continue
            result.append(str(item).strip())
        return [item for item in result if item]

    return [str(value).strip()]


def _claim_to_string(value):
    """Return a scalar claim as a string."""
    if isinstance(value, list):
        value = value[0] if value else None

    if value in (None, ""):
        return None

    return str(value).strip()


def _json_safe_claims(claims):
    """Convert claims to JSON-safe structure."""
    return json.loads(json.dumps(claims or {}, default=str))


def _email_domain(email):
    """Return lower-case email domain."""
    if not email or "@" not in email:
        return None
    return email.rsplit("@", 1)[1].lower()


def _validate_provider_policy(provider, claims, email):
    """Validate allowed domain and verified email policy."""
    allowed_domains = provider.allowed_domains or []
    if allowed_domains:
        domain = _email_domain(email)
        if not domain or domain not in [item.lower() for item in allowed_domains]:
            raise SsoLoginError(
                "sso_domain_denied",
                "This email domain is not allowed for this SSO provider",
                403,
            )

    if provider.protocol == "oidc" and provider.require_verified_email:
        email_verified = extract_claim(claims, "email_verified", None)
        if str(email_verified).lower() not in ("true", "1", "yes"):
            raise SsoLoginError(
                "sso_email_not_verified",
                "OIDC provider did not confirm that email is verified",
                403,
            )


def _sanitize_username(value):
    """Build a safe local username candidate."""
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9_.-]+", "-", value)
    value = value.strip(".-_")
    return value


def _unique_username(base):
    """Return unique username based on a candidate."""
    base = _sanitize_username(base) or "sso-user"
    candidate = base
    counter = 2

    while User.get_or_none((User.username == candidate) & (User.deleted == False)):
        candidate = f"{base}-{counter}"
        counter += 1

    return candidate


def _find_user_by_email(email):
    """Find one active non-deleted user by email."""
    if not email:
        return None

    matches = list(
        User
        .select()
        .where(
            (User.email == email)
            & (User.deleted == False)
        )
        .limit(2)
    )

    if len(matches) > 1:
        raise SsoLoginError(
            "sso_email_ambiguous",
            "More than one local user has this email address",
            409,
        )

    return matches[0] if matches else None


def _get_subject(provider, claims):
    """Return stable external subject for provider."""
    subject_claim = provider.subject_claim

    if provider.protocol == "saml" and subject_claim == "sub":
        subject_claim = "NameID"

    subject = _claim_to_string(extract_claim(claims, subject_claim))
    if not subject:
        raise SsoLoginError(
            "sso_subject_missing",
            f"SSO subject claim '{subject_claim}' was not found",
            400,
        )

    return subject


def _resolve_sso_user(provider, claims):
    """Find, link or create local user for SSO claims."""
    subject = _get_subject(provider, claims)

    email = _claim_to_string(extract_claim(claims, provider.email_claim))
    username = _claim_to_string(extract_claim(claims, provider.username_claim))
    display_name = _claim_to_string(extract_claim(claims, provider.display_name_claim))

    _validate_provider_policy(provider, claims, email)

    raw_claims = _json_safe_claims(claims)

    identity = SsoIdentity.get_or_none(
        (SsoIdentity.provider == provider.id)
        & (SsoIdentity.subject == subject)
    )

    if identity:
        user = identity.user
        if not user or user.deleted or not user.active:
            raise SsoLoginError(
                "sso_user_disabled",
                "Linked local user is disabled",
                403,
            )

        identity.email = email
        identity.username = username
        identity.raw_claims = raw_claims
        identity.last_login_at = datetime.utcnow()
        identity.save()

        return user

    user = None

    if provider.auto_link_by_email and email:
        user = _find_user_by_email(email)
        if user and (user.deleted or not user.active):
            raise SsoLoginError(
                "sso_user_disabled",
                "Local user with this email is disabled",
                403,
            )

    if not user:
        if not provider.auto_create_users:
            raise SsoLoginError(
                "sso_user_not_found",
                "No linked local user was found and auto-create is disabled",
                403,
            )

        local_username = _unique_username(username or (email.split("@", 1)[0] if email else subject))

        user = users_repo.create_user(
            username=local_username,
            display_name=display_name or local_username,
            email=email,
            password_hash=None,
            active=True,
            is_admin=False,
        )

    try:
        SsoIdentity.create(
            provider=provider.id,
            user=user.id,
            subject=subject,
            email=email,
            username=username,
            raw_claims=raw_claims,
            last_login_at=datetime.utcnow(),
        )
    except IntegrityError:
        identity = SsoIdentity.get(
            (SsoIdentity.provider == provider.id)
            & (SsoIdentity.subject == subject)
        )
        user = identity.user

    return user


def _fill_missing_user_fields(user, provider, claims):
    """Fill empty local user fields from SSO claims without overwriting manual data."""
    email = _claim_to_string(extract_claim(claims, provider.email_claim))
    display_name = _claim_to_string(extract_claim(claims, provider.display_name_claim))
    phone = _claim_to_string(extract_claim(claims, provider.phone_claim))

    update_data = {}

    if email and not user.email:
        update_data["email"] = email

    if display_name and not user.display_name:
        update_data["display_name"] = display_name

    if phone and not user.phone:
        try:
            phone = normalize_phone(phone)
        except ValueError:
            phone = None
        update_data["phone"] = phone

    if update_data:
        user = users_repo.update_user(user.id, update_data)

    return user


def _effective_group_role(mapping_role: str) -> str:
    """
    Convert SSO mapping role to a valid IncidentRelay group role.
    """
    if mapping_role == "global_admin":
        return "user_admin"

    return mapping_role


def _sync_team_membership_from_mapping(user, mapping):
    """Sync optional IncidentRelay team membership from a matched SSO mapping."""
    team_id = getattr(mapping, "incidentrelay_team_id", None)

    if not team_id:
        return

    teams_repo.add_user_to_team(
        team_id=team_id,
        user_id=user.id,
        role=mapping.team_role or "viewer",
    )


def _sync_group_memberships(user, provider, claims):
    """Sync IncidentRelay group memberships from SSO group mappings."""
    if not provider.sync_group_memberships:
        user, _active_group_ids = ensure_user_active_group(user)
        return

    external_groups_raw = normalize_groups(
        extract_claim(claims, provider.groups_claim)
    )
    external_groups = normalize_sso_group_set(external_groups_raw)

    mappings = list(
        SsoGroupMapping
        .select()
        .where(
            (SsoGroupMapping.provider == provider.id)
            & (SsoGroupMapping.active == True)
        )
        .order_by(SsoGroupMapping.priority.asc(), SsoGroupMapping.id.asc())
    )

    if not mappings:
        user, _active_group_ids = ensure_user_active_group(user)
        return

    if not external_groups and not provider.remove_missing_group_memberships:
        user, active_group_ids = ensure_user_active_group(user)

        if not active_group_ids and not user.is_admin:
            raise SsoLoginError(
                "sso_group_mapping_not_matched",
                (
                    "SSO login did not assign any IncidentRelay group. "
                    "Check the configured groups claim and SSO group mappings."
                ),
                403,
            )

        return

    provider_group_ids = []
    matched_group_ids = []

    for mapping in mappings:
        group_id = mapping.incidentrelay_group_id
        provider_group_ids.append(group_id)

        if normalize_sso_group_name(mapping.external_group) not in external_groups:
            continue

        groups_repo.add_user_to_group(
            user_id=user.id,
            group_id=group_id,
            role=_effective_group_role(mapping.group_role),
        )

        _sync_team_membership_from_mapping(user, mapping)

        matched_group_ids.append(group_id)

    if provider.remove_missing_group_memberships and provider_group_ids:
        query = (
            (UserGroup.user == user.id)
            & (UserGroup.group.in_(provider_group_ids))
        )

        if matched_group_ids:
            query = query & (~(UserGroup.group.in_(matched_group_ids)))

        UserGroup.update(active=False).where(query).execute()

    _sync_global_admin(user, mappings, external_groups)

    user = users_repo.get_user(user.id)
    user, active_group_ids = ensure_user_active_group(user)

    if not active_group_ids and not user.is_admin:
        raise SsoLoginError(
            "sso_group_mapping_not_matched",
            (
                "SSO login did not assign any IncidentRelay group. "
                "Check the configured groups claim and SSO group mappings."
            ),
            403,
        )


def _sync_global_admin(user, mappings, external_groups):
    """
    Synchronize global admin access from SSO mappings.
    """
    admin_mappings = [
        mapping
        for mapping in mappings
        if mapping.active and mapping.group_role == "global_admin"
    ]

    if not admin_mappings:
        return

    should_be_admin = any(
        normalize_sso_group_name(mapping.external_group) in external_groups
        for mapping in admin_mappings
    )

    if user.is_admin != should_be_admin:
        user.is_admin = should_be_admin
        user.save()


def complete_sso_login(provider, claims):
    """Resolve local user and apply SSO group mappings."""
    with db.atomic():
        user = _resolve_sso_user(provider, claims)
        user = _fill_missing_user_fields(user, provider, claims)
        _sync_group_memberships(user, provider, claims)
        return users_repo.get_user(user.id)
