"""Central API-token scope definitions and request-to-scope mapping.

Keep this module dependency-free: it is imported by middleware, profile token
creation, integration authentication, tests, and documentation helpers.
"""

import re

READ_METHODS = frozenset({"GET", "HEAD"})
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

PUBLIC_API_PATHS = frozenset({
    "/api/auth/login",
    "/api/auth/logout",
    "/api/push/actions",
})

PUBLIC_API_PREFIXES = (
    "/api/auth/sso",
    "/api/integrations",
    "/api/heartbeats/ping",
    "/api/version",
)

# Stable, user-facing granular scopes. Keep the order intentional because the
# profile API returns this sequence to the UI.
READ_WRITE_SCOPE_DOMAINS = (
    "changes",
    "change-integrations",
    "directory-sync",
    "system-settings",
    "alerts",
    "incidents",
    "services",
    "teams",
    "groups",
    "users",
    "rotations",
    "calendar",
    "routes",
    "channels",
    "maintenance",
    "heartbeats",
    "policies",
    "orchestrations",
    "sso",
    "profile",
)
READ_ONLY_SCOPE_DOMAINS = ("audit",)

GRANULAR_READ_SCOPES = tuple(
    f"{domain}:read"
    for domain in (*READ_WRITE_SCOPE_DOMAINS, *READ_ONLY_SCOPE_DOMAINS)
)
GRANULAR_WRITE_SCOPES = tuple(
    f"{domain}:write"
    for domain in READ_WRITE_SCOPE_DOMAINS
)

LEGACY_AGGREGATE_SCOPES = ("resources:read", "resources:write")

PROFILE_TOKEN_SCOPE_OPTIONS = (
    *GRANULAR_READ_SCOPES,
    *GRANULAR_WRITE_SCOPES,
    *LEGACY_AGGREGATE_SCOPES,
    "*",
)
ALLOWED_PROFILE_TOKEN_SCOPES = frozenset(PROFILE_TOKEN_SCOPE_OPTIONS)

# resources:* predates granular entity scopes. Preserve it as an aggregate for
# the explicitly listed resource domains so existing tokens keep working.
# Changes and administrative settings/integrations require dedicated scopes.
# alerts:* and profile:* remain separate exactly as they were before.
LEGACY_RESOURCE_DOMAINS = frozenset({
    "incidents",
    "services",
    "teams",
    "groups",
    "users",
    "rotations",
    "calendar",
    "routes",
    "channels",
    "maintenance",
    "heartbeats",
    "policies",
    "orchestrations",
    "audit",
    "sso",
})

# Ordered longest/specialized prefixes first. Values are scope domains; method
# determines :read vs :write. Related internal resources deliberately share a
# stable public domain (e.g. business services -> services, silences ->
# maintenance, matcher/policy endpoints -> policies).
API_SCOPE_RULES = (
    # OpenAPI specification follows the authenticated documentation boundary.
    # Reuse profile:read rather than adding a one-off docs scope.
    ("/api/openapi.json", "profile"),
    ("/api/admin/change-integrations", "change-integrations"),
    ("/api/admin/directory-sync", "directory-sync"),
    ("/api/admin/system-settings", "system-settings"),
    ("/api/admin/audit-logs", "audit"),
    ("/api/admin/sso", "sso"),
    ("/api/admin/users", "users"),
    ("/api/orchestration-webhook-actions", "orchestrations"),
    ("/api/event-orchestrations", "orchestrations"),
    ("/api/notification-policies", "policies"),
    ("/api/priority-policies", "policies"),
    ("/api/escalation-policies", "policies"),
    ("/api/matcher-presets", "policies"),
    ("/api/matchers", "policies"),
    ("/api/maintenance-windows", "maintenance"),
    ("/api/business-services", "services"),
    ("/api/notification-center", "profile"),
    ("/api/oncall-health", "rotations"),
    ("/api/heartbeats", "heartbeats"),
    ("/api/incidents", "incidents"),
    ("/api/services", "services"),
    ("/api/silences", "maintenance"),
    ("/api/rotations", "rotations"),
    ("/api/calendar", "calendar"),
    ("/api/channels", "channels"),
    ("/api/routes", "routes"),
    ("/api/teams", "teams"),
    ("/api/groups", "groups"),
    ("/api/users", "users"),
    ("/api/alert-groups", "alerts"),
    ("/api/profile", "profile"),
    # /api/auth/me and /api/auth/change-password are JWT-only at the view
    # layer. Mapping them to profile still keeps middleware fail-closed and
    # produces a meaningful scope error before the JWT-only decorator runs.
    ("/api/auth", "profile"),
)


def path_matches_prefix(path, prefix):
    """Return True when path is exactly prefix or is a child path."""
    return path == prefix or path.startswith(prefix + "/")


def is_public_calendar_feed_path(path, method):
    """Return True for tokenized public ICS subscription URLs only."""
    method = str(method or "").upper()

    if method not in READ_METHODS:
        return False

    prefix = "/api/calendar/feeds/"
    if not path.startswith(prefix):
        return False

    rest = path[len(prefix):]
    return bool(rest) and rest.endswith(".ics") and "/" not in rest


def is_public_api_request(path, method):
    """Return True when global API auth middleware must not handle request."""
    if path in PUBLIC_API_PATHS:
        return True

    if is_public_calendar_feed_path(path, method):
        return True

    return any(path_matches_prefix(path, prefix) for prefix in PUBLIC_API_PREFIXES)


def required_scopes_for_path(path, method):
    """Return required scopes for one protected API request.

    None means the request has no configured API-token scope mapping and must
    therefore be denied for API-token principals (fail closed).
    """
    method = str(method or "").upper()
    if path == "/api/change-events":
        return ["changes:ingest"] if method == "POST" else None
    if re.fullmatch(r"/api/alert-groups/\d+/(episodes|related-changes)", path):
        return ["changes:read", "alerts:read"] if method in READ_METHODS else None
    if re.fullmatch(r"/api/incidents/\d+/changes(?:/\d+)?", path):
        item = bool(re.fullmatch(r"/api/incidents/\d+/changes/\d+", path))
        if method in READ_METHODS and not item:
            return ["changes:read", "incidents:read"]
        if (method == "POST" and not item) or (item and method in {"PATCH", "DELETE"}):
            return ["changes:write", "incidents:write"]
        return None
    if re.match(r"/api/incidents/\d+/changes(?:/|$)", path):
        return None
    if path_matches_prefix(path, "/api/changes"):
        change_path = r"/api/changes/[0-9a-fA-F-]{36}"
        if re.fullmatch(change_path + r"/(correlations|correlation-targets)", path) and method in READ_METHODS:
            return ["changes:read", "alerts:read"]
        if re.fullmatch(change_path + r"/correlations(?:/\d+/review)?", path) and method == "POST":
            return ["changes:write", "alerts:write"]
        if re.fullmatch(change_path + r"/incidents", path) and method in READ_METHODS:
            return ["changes:read", "incidents:read"]
        known_read = path in ("/api/changes", "/api/changes/sources") or re.fullmatch(
            r"/api/changes/[0-9a-fA-F-]{36}(?:/events|/services)?", path
        )
        return ["changes:read"] if known_read and method in READ_METHODS else None
    if re.fullmatch(r"/api/services/\d+/changes", path):
        return ["changes:read", "services:read"] if method in READ_METHODS else None
    action = None
    if method in READ_METHODS:
        action = "read"
    elif method in WRITE_METHODS:
        action = "write"

    if action is None:
        return None

    for prefix, domain in API_SCOPE_RULES:
        if not path_matches_prefix(path, prefix):
            continue

        scope = f"{domain}:{action}"
        if scope not in ALLOWED_PROFILE_TOKEN_SCOPES:
            # Read-only domains (currently audit) intentionally have no write
            # scope. A write request therefore remains fail closed.
            return None

        return [scope]

    return None


def expand_token_scopes(scopes):
    """Expand legacy aggregate scopes into their granular effective scopes."""
    raw = set(scopes or [])
    effective = set(raw)

    if "*" in raw:
        effective.update(ALLOWED_PROFILE_TOKEN_SCOPES)
        return effective

    if "resources:read" in raw:
        effective.update(
            f"{domain}:read"
            for domain in LEGACY_RESOURCE_DOMAINS
            if f"{domain}:read" in ALLOWED_PROFILE_TOKEN_SCOPES
        )

    if "resources:write" in raw:
        effective.update(
            f"{domain}:write"
            for domain in LEGACY_RESOURCE_DOMAINS
            if f"{domain}:write" in ALLOWED_PROFILE_TOKEN_SCOPES
        )

    return effective


def token_has_scopes(token_scopes, required_scopes):
    """Return True when token scopes satisfy every required scope."""
    if not required_scopes:
        return True

    raw = set(token_scopes or [])
    if "changes:ingest" in required_scopes and "changes:ingest" not in raw:
        return False
    if "*" in raw:
        # Wildcard keeps its historical meaning for explicitly declared view
        # scopes. Unmapped API routes are rejected before this check.
        return True

    effective = expand_token_scopes(raw)
    return all(scope in effective for scope in required_scopes)


def token_can_grant_scopes(current_scopes, requested_scopes):
    """Return True when a token may mint another token with requested scopes.

    Granular scopes may be delegated through a matching legacy resources:*
    aggregate. Aggregate scopes themselves may only be delegated by the same
    aggregate (or wildcard) so a granular token cannot manufacture a broader
    future-facing aggregate scope.
    """
    current = set(current_scopes or [])
    requested = set(requested_scopes or [])

    if "*" in current:
        return True

    for scope in requested:
        if scope == "*":
            return False

        if scope in LEGACY_AGGREGATE_SCOPES:
            if scope not in current:
                return False
            continue

        if not token_has_scopes(current, [scope]):
            return False

    return True
