import json
import secrets
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from authlib.integrations.requests_client import OAuth2Session
from flask import Blueprint, Response, jsonify, redirect, request, session
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.settings import OneLogin_Saml2_Settings
from authlib.jose import JsonWebKey, JsonWebToken
from authlib.jose.errors import JoseError as AuthlibJoseError
from joserfc.errors import JoseError as JoseRFCError
from authlib.oidc.core import CodeIDToken

from app.modules.db import sso_repo
from app.services.audit import write_audit
from app.modules.sso.crypto import decrypt_secret
from app.modules.sso.sso_login import (
    SsoLoginError,
    build_sso_login_response,
    complete_sso_login,
)
from app.login import normalize_auth_redirect_target
from app.settings import Config
from app.modules.sso.saml_security import get_saml_security, validate_saml_crypto_config
from app.services.validation import safe_exception_response

sso_auth_bp = Blueprint("sso_auth_api", __name__)


def _public_sso_url(slug, suffix):
    """Build public SSO URL from configured public base URL."""
    return f"{Config.PUBLIC_BASE_URL.rstrip('/')}/api/auth/sso/{slug}/{suffix}"


def _get_enabled_provider(slug):
    """Return enabled provider or API error."""
    provider = sso_repo.get_provider_by_slug(slug, enabled_only=True)
    if not provider:
        return None, (jsonify({
            "error": "sso_provider_not_found",
            "message": "SSO provider was not found or is disabled",
        }), 404)

    return provider, None


def _safe_provider(provider):
    """Serialize public provider data."""
    return {
        "slug": provider.slug,
        "label": provider.label,
        "protocol": provider.protocol,
        "enabled": provider.enabled,
    }


@sso_auth_bp.route("/providers", methods=["GET"])
def public_sso_providers():
    """Return enabled SSO providers for login page."""
    providers = sso_repo.list_providers(include_disabled=False)
    return jsonify([_safe_provider(provider) for provider in providers])


def _load_json_url(url, error_code, error_message):
    """Load JSON document from URL."""
    try:
        req = UrlRequest(
            url,
            headers={"Accept": "application/json"},
        )
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SsoLoginError(
            error_code,
            error_message,
            502,
        ) from exc


def _load_oidc_metadata(provider):
    """Load OIDC metadata document."""
    if not provider.oidc_metadata_url:
        return {}

    return _load_json_url(
        provider.oidc_metadata_url,
        "sso_oidc_metadata_error",
        "Could not load OIDC metadata",
    )


def _load_oidc_jwks(provider, metadata):
    """Load OIDC JWKS document."""
    jwks_uri = provider.oidc_jwks_uri or metadata.get("jwks_uri")

    if not jwks_uri:
        raise SsoLoginError(
            "sso_oidc_jwks_missing",
            "OIDC JWKS URI is not configured",
            400,
        )

    return _load_json_url(
        jwks_uri,
        "sso_oidc_jwks_error",
        "Could not load OIDC JWKS",
    )


def _oidc_allowed_algs(metadata):
    """Return allowed ID token signing algorithms."""
    algs = metadata.get("id_token_signing_alg_values_supported") or ["RS256"]
    return [alg for alg in algs if alg and alg.lower() != "none"]


def _validate_oidc_id_token(provider, metadata, token, expected_nonce):
    """Validate OIDC id_token and return trusted claims."""
    id_token = token.get("id_token")
    if not id_token:
        raise SsoLoginError(
            "sso_oidc_id_token_missing",
            "OIDC token response did not contain id_token",
            400,
        )

    issuer = provider.oidc_issuer or metadata.get("issuer")
    if not issuer:
        raise SsoLoginError(
            "sso_oidc_issuer_missing",
            "OIDC issuer is not configured",
            400,
        )

    if not provider.client_id:
        raise SsoLoginError(
            "sso_oidc_client_id_missing",
            "OIDC client_id is not configured",
            400,
        )

    if not expected_nonce:
        raise SsoLoginError(
            "sso_oidc_nonce_missing",
            "OIDC nonce is missing or expired",
            400,
        )

    allowed_algs = _oidc_allowed_algs(metadata)
    if not allowed_algs:
        raise SsoLoginError(
            "sso_oidc_alg_missing",
            "OIDC provider did not expose supported signing algorithms",
            400,
        )

    jwks = _load_oidc_jwks(provider, metadata)
    key_set = JsonWebKey.import_key_set(jwks)

    jwt_decoder = JsonWebToken(allowed_algs)

    claims_options = {
        "iss": {
            "essential": True,
            "values": [issuer],
        },
        "sub": {
            "essential": True,
        },
        "exp": {
            "essential": True,
        },
        "iat": {
            "essential": True,
        },
    }

    claims_params = {
        "client_id": provider.client_id,
        "nonce": expected_nonce,
        "access_token": token.get("access_token"),
    }

    try:
        claims = jwt_decoder.decode(
            id_token,
            key=key_set,
            claims_cls=CodeIDToken,
            claims_options=claims_options,
            claims_params=claims_params,
        )
        claims.validate(leeway=120)
    except (AuthlibJoseError, JoseRFCError) as exc:
        raise SsoLoginError(
            "sso_oidc_id_token_invalid",
            "OIDC id_token validation failed",
            401,
        ) from exc

    return dict(claims)


def _fetch_oidc_userinfo(provider, metadata, token):
    """Fetch OIDC userinfo claims if endpoint is configured."""
    userinfo_endpoint = _oidc_endpoint(
        provider,
        metadata,
        "oidc_userinfo_endpoint",
        "userinfo_endpoint",
    )

    if not userinfo_endpoint:
        return {}

    client_secret = decrypt_secret(provider.client_secret_encrypted)

    try:
        userinfo_client = OAuth2Session(
            client_id=provider.client_id,
            client_secret=client_secret,
            token=token,
        )

        response = userinfo_client.get(userinfo_endpoint)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        raise SsoLoginError(
            "sso_oidc_userinfo_failed",
            "Could not fetch OIDC userinfo",
            502,
        ) from exc


def _merge_oidc_claims(id_token_claims, userinfo_claims):
    """Merge userinfo claims with trusted id_token claims."""
    claims = dict(userinfo_claims or {})

    userinfo_sub = claims.get("sub")
    id_token_sub = id_token_claims.get("sub")

    if userinfo_sub and id_token_sub and str(userinfo_sub) != str(id_token_sub):
        raise SsoLoginError(
            "sso_oidc_subject_mismatch",
            "OIDC userinfo subject does not match id_token subject",
            401,
        )

    claims.update(id_token_claims)
    return claims


def _oidc_endpoint(provider, metadata, field_name, metadata_key):
    """Return OIDC endpoint from provider config or metadata."""
    return getattr(provider, field_name) or metadata.get(metadata_key)


def _oidc_login(provider):
    """Start OIDC login flow."""
    metadata = _load_oidc_metadata(provider)

    authorization_endpoint = _oidc_endpoint(
        provider,
        metadata,
        "oidc_authorization_endpoint",
        "authorization_endpoint",
    )

    if not authorization_endpoint:
        return jsonify({
            "error": "sso_oidc_not_configured",
            "message": "OIDC authorization endpoint is not configured",
        }), 400

    callback_url = _public_sso_url(provider.slug, "callback")
    client_secret = decrypt_secret(provider.client_secret_encrypted)

    oauth = OAuth2Session(
        client_id=provider.client_id,
        client_secret=client_secret,
        scope=provider.oidc_scope,
        redirect_uri=callback_url,
    )

    nonce = secrets.token_urlsafe(24)
    authorization_url, state = oauth.create_authorization_url(
        authorization_endpoint,
        nonce=nonce,
    )

    session[f"sso_oidc_state:{provider.slug}"] = state
    session[f"sso_oidc_nonce:{provider.slug}"] = nonce
    session[f"sso_return_to:{provider.slug}"] = normalize_auth_redirect_target(
        request.args.get("next")
    )

    return redirect(authorization_url)


def _oidc_callback(provider):
    """Complete OIDC login flow."""
    if request.args.get("error"):
        return jsonify({
            "error": "sso_oidc_error",
            "message": request.args.get("error_description") or request.args.get("error"),
        }), 400

    expected_state = session.pop(f"sso_oidc_state:{provider.slug}", None)
    expected_nonce = session.pop(f"sso_oidc_nonce:{provider.slug}", None)
    redirect_to = session.pop(f"sso_return_to:{provider.slug}", "/")

    if not expected_state or request.args.get("state") != expected_state:
        return jsonify({
            "error": "sso_oidc_state_invalid",
            "message": "OIDC state is invalid or expired",
        }), 400

    metadata = _load_oidc_metadata(provider)

    token_endpoint = _oidc_endpoint(
        provider,
        metadata,
        "oidc_token_endpoint",
        "token_endpoint",
    )

    if not token_endpoint:
        return jsonify({
            "error": "sso_oidc_not_configured",
            "message": "OIDC token endpoint is required",
        }), 400

    callback_url = _public_sso_url(provider.slug, "callback")
    authorization_response = f"{callback_url}?{request.query_string.decode('utf-8')}"
    client_secret = decrypt_secret(provider.client_secret_encrypted)

    try:
        oauth = OAuth2Session(
            client_id=provider.client_id,
            client_secret=client_secret,
            scope=provider.oidc_scope,
            redirect_uri=callback_url,
            state=expected_state,
        )

        token = oauth.fetch_token(
            token_endpoint,
            authorization_response=authorization_response,
        )

        id_token_claims = _validate_oidc_id_token(
            provider=provider,
            metadata=metadata,
            token=token,
            expected_nonce=expected_nonce,
        )

        userinfo_claims = _fetch_oidc_userinfo(
            provider=provider,
            metadata=metadata,
            token=token,
        )

        claims = _merge_oidc_claims(
            id_token_claims=id_token_claims,
            userinfo_claims=userinfo_claims,
        )

    except SsoLoginError as exc:
        return jsonify({
            "error": exc.error,
            "message": exc.message,
        }), exc.status_code
    except Exception as exc:
        return safe_exception_response(
            exc,
            error="sso_oidc_callback_failed",
            message="OIDC callback failed.",
            status_code=502,
        )

    try:
        user = complete_sso_login(provider, claims)
    except SsoLoginError as exc:
        return jsonify({
            "error": exc.error,
            "message": exc.message,
        }), exc.status_code

    write_audit(
        "sso.login",
        object_type="user",
        object_id=user.id,
        user_id=user.id,
        data={
            "provider_id": provider.id,
            "provider_slug": provider.slug,
            "protocol": provider.protocol,
        },
    )

    return build_sso_login_response(user, redirect_to=redirect_to)


def _saml_request_data():
    """Prepare Flask request for python3-saml."""
    forwarded_proto = request.headers.get("X-Forwarded-Proto", request.scheme)
    scheme = forwarded_proto.split(",", 1)[0].strip()

    return {
        "https": "on" if scheme == "https" else "off",
        "http_host": request.host,
        "server_port": request.environ.get("SERVER_PORT"),
        "script_name": request.path,
        "get_data": request.args.copy(),
        "post_data": request.form.copy(),
        "query_string": request.query_string.decode("utf-8"),
    }


def _build_saml_settings(provider):
    """Build python3-saml settings from SSO provider."""
    sp_entity_id = provider.saml_sp_entity_id or _public_sso_url(provider.slug, "metadata")
    sp_acs_url = provider.saml_sp_acs_url or _public_sso_url(provider.slug, "callback")
    sp_private_key = decrypt_secret(provider.saml_sp_private_key_encrypted) or ""
    security = get_saml_security(provider.extra_config)

    validate_saml_crypto_config(provider, security, sp_private_key)

    sp_settings = {
        "entityId": sp_entity_id,
        "assertionConsumerService": {
            "url": sp_acs_url,
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
        },
        "NameIDFormat": provider.saml_name_id_format,
        "x509cert": provider.saml_sp_x509_cert or "",
        "privateKey": sp_private_key,
    }

    if provider.saml_sp_sls_url:
        sp_settings["singleLogoutService"] = {
            "url": provider.saml_sp_sls_url,
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
        }

    idp_settings = {
        "entityId": provider.saml_idp_entity_id,
        "singleSignOnService": {
            "url": provider.saml_idp_sso_url,
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
        },
        "x509cert": provider.saml_idp_x509_cert or "",
    }

    if provider.saml_idp_slo_url:
        idp_settings["singleLogoutService"] = {
            "url": provider.saml_idp_slo_url,
            "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
        }

    return {
        "strict": True,
        "debug": False,
        "sp": sp_settings,
        "idp": idp_settings,
        "security": security,
    }


def _saml_login(provider):
    """Start SAML login flow."""
    if not provider.saml_idp_entity_id or not provider.saml_idp_sso_url:
        return jsonify({
            "error": "sso_saml_not_configured",
            "message": "SAML IdP entity ID and SSO URL are required",
        }), 400

    try:
        settings = _build_saml_settings(provider)
    except SsoLoginError as exc:
        return jsonify({
            "error": exc.error,
            "message": exc.message,
        }), exc.status_code

    auth = OneLogin_Saml2_Auth(
        _saml_request_data(),
        old_settings=settings,
    )

    session[f"sso_return_to:{provider.slug}"] = normalize_auth_redirect_target(
        request.args.get("next")
    )

    return redirect(auth.login())


def _flatten_saml_attributes(provider, attributes, name_id):
    """Convert SAML attributes to claims."""
    claims = {}

    for key, value in (attributes or {}).items():
        if key == provider.groups_claim:
            claims[key] = value
        elif isinstance(value, list) and len(value) == 1:
            claims[key] = value[0]
        else:
            claims[key] = value

    claims["NameID"] = name_id

    return claims


def _saml_callback(provider):
    """Complete SAML login flow."""
    try:
        settings = _build_saml_settings(provider)
    except SsoLoginError as exc:
        return jsonify({
            "error": exc.error,
            "message": exc.message,
        }), exc.status_code

    auth = OneLogin_Saml2_Auth(
        _saml_request_data(),
        old_settings=settings,
    )

    auth.process_response()

    errors = auth.get_errors()
    if errors:
        return jsonify({
            "error": "sso_saml_callback_failed",
            "message": "; ".join(errors),
            "reason": auth.get_last_error_reason(),
        }), 400

    if not auth.is_authenticated():
        return jsonify({
            "error": "sso_saml_not_authenticated",
            "message": "SAML response was not authenticated",
        }), 401

    claims = _flatten_saml_attributes(
        provider,
        auth.get_attributes(),
        auth.get_nameid(),
    )

    redirect_to = session.pop(f"sso_return_to:{provider.slug}", "/")

    try:
        user = complete_sso_login(provider, claims)
    except SsoLoginError as exc:
        return jsonify({
            "error": exc.error,
            "message": exc.message,
        }), exc.status_code

    write_audit(
        "sso.login",
        object_type="user",
        object_id=user.id,
        user_id=user.id,
        data={
            "provider_id": provider.id,
            "provider_slug": provider.slug,
            "protocol": provider.protocol,
        },
    )

    return build_sso_login_response(user, redirect_to=redirect_to)


@sso_auth_bp.route("/<slug>/login", methods=["GET"])
def sso_login(slug):
    """Start SSO login for provider."""
    provider, error = _get_enabled_provider(slug)
    if error:
        return error

    if provider.protocol == "oidc":
        return _oidc_login(provider)

    if provider.protocol == "saml":
        return _saml_login(provider)

    return jsonify({
        "error": "sso_protocol_unsupported",
        "message": "Unsupported SSO protocol",
    }), 400


@sso_auth_bp.route("/<slug>/callback", methods=["GET", "POST"])
def sso_callback(slug):
    """Complete SSO login for provider."""
    provider, error = _get_enabled_provider(slug)
    if error:
        return error

    if provider.protocol == "oidc":
        return _oidc_callback(provider)

    if provider.protocol == "saml":
        return _saml_callback(provider)

    return jsonify({
        "error": "sso_protocol_unsupported",
        "message": "Unsupported SSO protocol",
    }), 400


@sso_auth_bp.route("/<slug>/metadata", methods=["GET"])
def saml_metadata(slug):
    """Return SAML SP metadata for provider."""
    provider, error = _get_enabled_provider(slug)
    if error:
        return error

    if provider.protocol != "saml":
        return jsonify({
            "error": "sso_metadata_not_supported",
            "message": "Metadata is available only for SAML providers",
        }), 400

    try:
        saml_settings = _build_saml_settings(provider)
    except SsoLoginError as exc:
        return jsonify({
            "error": exc.error,
            "message": exc.message,
        }), exc.status_code

    settings = OneLogin_Saml2_Settings(
        saml_settings,
        sp_validation_only=True,
    )

    metadata = settings.get_sp_metadata()
    errors = settings.validate_metadata(metadata)

    if errors:
        return jsonify({
            "error": "sso_saml_metadata_invalid",
            "message": "; ".join(errors),
        }), 500

    return Response(metadata, mimetype="application/xml")
