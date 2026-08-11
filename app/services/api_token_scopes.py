"""Central API-token scope definitions and request-to-scope mapping.

Keep this module dependency-free: it is imported by middleware, profile token
creation, integration authentication, tests, and documentation helpers.
"""

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
# every non-alert, non-profile resource domain so existing tokens keep working.
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
    ("/api/alerts", "alerts"),
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
