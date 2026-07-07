from html import escape as html_escape
from typing import Any
from types import SimpleNamespace

from app.modules.db import services_repo
from app.services.routing.matcher.match_context import alert_rule_matches


MAX_SERVICE_CONTEXT_ITEMS = 5
INTEGRATION_RUNBOOK_URL_KEYS = (
    "runbook_url",
    "runbook",
    "runbook_link",
    "runbookUrl",
    "runbookURL",
    "playbook_url",
    "playbook",
)

INTEGRATION_RUNBOOK_TITLE_KEYS = (
    "runbook_title",
    "runbook_name",
    "playbook_title",
    "playbook_name",
)


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return text


def _display_name(*values: Any, default: str = "-") -> str:
    for value in values:
        text = _clean(value)
        if text:
            return text
    return default


def service_display_name(alert_or_service: Any) -> str:
    """Return service display name using name first, then slug."""
    service = getattr(alert_or_service, "service", None) or alert_or_service

    if not service:
        service_id = getattr(alert_or_service, "service_id", None)
        return f"Service #{service_id}" if service_id else "-"

    return _display_name(
        getattr(service, "name", None),
        getattr(service, "slug", None),
        f"Service #{getattr(service, 'id', '-')}",
    )


def _alert_service_id(alert: Any) -> int | None:
    service_id = getattr(alert, "service_id", None)
    if service_id:
        return service_id

    service = getattr(alert, "service", None)
    return getattr(service, "id", None) if service else None


def get_alert_service_links(alert: Any, limit: int = MAX_SERVICE_CONTEXT_ITEMS) -> list:
    """Return enabled service links for alert service."""
    service_id = _alert_service_id(alert)
    if not service_id:
        return []

    links = services_repo.list_service_links(service_id=service_id)
    return [
        link
        for link in links
        if getattr(link, "enabled", True) and not getattr(link, "deleted", False)
    ][:limit]


def _runbook_matches_alert(runbook: Any, alert: Any) -> bool:
    runbook_severity = _clean(getattr(runbook, "severity", None)).lower()
    alert_severity = _clean(getattr(alert, "severity", None)).lower()

    if runbook_severity and runbook_severity != alert_severity:
        return False

    try:
        return alert_rule_matches(
            alert,
            runbook,
            team=getattr(alert, "team", None),
            route=getattr(alert, "route", None),
            service=getattr(alert, "service", None),
            priority=getattr(alert, "priority_slug", None),
        )
    except Exception:
        return False


def _first_text_value(*values: Any) -> str:
    """Return first non-empty text value."""
    for value in values:
        text = _clean(value)
        if text:
            return text
    return ""


def _first_mapping_value(mapping: dict, keys: tuple[str, ...]) -> Any:
    """Return first value from mapping by known keys."""
    if not isinstance(mapping, dict):
        return None

    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value

    return None


def _integration_runbook_title(payload: dict, labels: dict, annotations: dict) -> str:
    """Return title for runbook passed by integration payload."""
    return _first_text_value(
        _first_mapping_value(annotations, INTEGRATION_RUNBOOK_TITLE_KEYS),
        _first_mapping_value(labels, INTEGRATION_RUNBOOK_TITLE_KEYS),
        _first_mapping_value(payload, INTEGRATION_RUNBOOK_TITLE_KEYS),
        "Integration runbook",
    )


def _integration_runbook_from_value(
    value: Any,
    *,
    payload: dict,
    labels: dict,
    annotations: dict,
    severity: str | None,
):
    """Build synthetic runbook object from integration-provided value."""
    if isinstance(value, dict):
        url = _first_text_value(
            value.get("url"),
            value.get("href"),
            value.get("link"),
        )
        title = _first_text_value(
            value.get("title"),
            value.get("name"),
            _integration_runbook_title(payload, labels, annotations),
        )
    else:
        url = _clean(value)
        title = _integration_runbook_title(payload, labels, annotations)

    if not url and not title:
        return None

    return SimpleNamespace(
        id=None,
        title=title or "Integration runbook",
        description=None,
        url=url,
        severity=severity,
        matchers={},
        priority=0,
        enabled=True,
        deleted=False,
        source="integration",
    )


def get_alert_integration_runbooks(alert: Any) -> list:
    """Return runbooks passed directly by integration payload."""
    payload = getattr(alert, "payload", None) or {}
    labels = getattr(alert, "labels", None) or {}

    if not isinstance(payload, dict):
        payload = {}

    if not isinstance(labels, dict):
        labels = {}

    annotations = payload.get("annotations") or {}
    if not isinstance(annotations, dict):
        annotations = {}

    severity = getattr(alert, "severity", None)

    values = [
        _first_mapping_value(annotations, INTEGRATION_RUNBOOK_URL_KEYS),
        _first_mapping_value(labels, INTEGRATION_RUNBOOK_URL_KEYS),
        _first_mapping_value(payload, INTEGRATION_RUNBOOK_URL_KEYS),
    ]

    # Optional structured form:
    #
    # "runbook": {
    #   "title": "...",
    #   "url": "..."
    # }
    structured = payload.get("runbook")
    if isinstance(structured, dict):
        values.insert(0, structured)

    runbooks = []
    seen = set()

    for value in values:
        if value in (None, ""):
            continue

        runbook = _integration_runbook_from_value(
            value,
            payload=payload,
            labels=labels,
            annotations=annotations,
            severity=severity,
        )

        if not runbook:
            continue

        key = (
            _clean(getattr(runbook, "url", None)),
            _clean(getattr(runbook, "title", None)),
        )

        if key in seen:
            continue

        seen.add(key)
        runbooks.append(runbook)

    return runbooks


def get_alert_service_runbooks(alert: Any, limit: int = MAX_SERVICE_CONTEXT_ITEMS) -> list:
    """Return integration-provided and service runbooks matching this alert."""
    integration_runbooks = get_alert_integration_runbooks(alert)

    service_id = _alert_service_id(alert)
    service_runbooks = []

    if service_id:
        service_runbooks = services_repo.list_service_runbooks(service_id=service_id)

    matched_service_runbooks = [
        runbook
        for runbook in service_runbooks
        if getattr(runbook, "enabled", True)
        and not getattr(runbook, "deleted", False)
        and _runbook_matches_alert(runbook, alert)
    ]

    result = []
    seen = set()

    # Put integration runbook first because it came with the exact alert.
    for runbook in integration_runbooks + matched_service_runbooks:
        key = (
            _clean(getattr(runbook, "url", None)),
            _clean(getattr(runbook, "title", None)),
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(runbook)

    return result[:limit]


def link_display_label(link: Any) -> str:
    """Return link label using label first, then url."""
    return _display_name(
        getattr(link, "label", None),
        getattr(link, "url", None),
        f"Link #{getattr(link, 'id', '-')}",
    )


def runbook_display_label(runbook: Any) -> str:
    """Return runbook label using title first, then url."""
    severity = _clean(getattr(runbook, "severity", None))
    title = _display_name(
        getattr(runbook, "title", None),
        getattr(runbook, "url", None),
        f"Runbook #{getattr(runbook, 'id', '-')}",
    )

    if severity:
        return f"{title} ({severity})"

    return title


def format_service_context_plain(alert: Any) -> list[str]:
    """Return plain text service links/runbooks lines."""
    links = get_alert_service_links(alert)
    runbooks = get_alert_service_runbooks(alert)

    lines: list[str] = []

    if links:
        lines.append("Links:")
        for link in links:
            label = link_display_label(link)
            url = _clean(getattr(link, "url", None))
            lines.append(f"- {label}: {url}" if url else f"- {label}")

    if runbooks:
        if lines:
            lines.append("")
        lines.append("Runbooks:")
        for runbook in runbooks:
            label = runbook_display_label(runbook)
            url = _clean(getattr(runbook, "url", None))
            lines.append(f"- {label}: {url}" if url else f"- {label}")

    return lines


def format_service_links_markdown(alert: Any) -> str:
    """Return Mattermost/Markdown service links."""
    lines = []
    for link in get_alert_service_links(alert):
        label = link_display_label(link)
        url = _clean(getattr(link, "url", None))
        lines.append(f"- [{label}]({url})" if url else f"- {label}")
    return "\n".join(lines)


def format_service_runbooks_markdown(alert: Any) -> str:
    """Return Mattermost/Markdown service runbooks."""
    lines = []
    for runbook in get_alert_service_runbooks(alert):
        label = runbook_display_label(runbook)
        url = _clean(getattr(runbook, "url", None))
        lines.append(f"- [{label}]({url})" if url else f"- {label}")
    return "\n".join(lines)


def format_service_links_html(alert: Any) -> str:
    """Return safe HTML service links."""
    lines = []
    for link in get_alert_service_links(alert):
        label = html_escape(link_display_label(link), quote=False)
        url = html_escape(_clean(getattr(link, "url", None)), quote=True)
        lines.append(f'<a href="{url}">{label}</a>' if url else label)
    return "<br>".join(lines) or "-"


def format_service_runbooks_html(alert: Any) -> str:
    """Return safe HTML service runbooks."""
    lines = []
    for runbook in get_alert_service_runbooks(alert):
        label = html_escape(runbook_display_label(runbook), quote=False)
        url = html_escape(_clean(getattr(runbook, "url", None)), quote=True)
        lines.append(f'<a href="{url}">{label}</a>' if url else label)
    return "<br>".join(lines) or "-"
