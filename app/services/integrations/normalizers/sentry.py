from app.services.integrations.normalizers.common import first_non_empty, first_event_link, add_event_link_label, \
    make_dedup_key

import logging

logger = logging.getLogger("oncall.alerts")


def sentry_link_candidates(*objects):
    """Yield URL-like values from nested Sentry payload objects."""
    url_keys = (
        "permalink",
        "web_url",
        "url",
        "issue_url",
        "event_url",
        "alert_url",
        "source_url",
        "link",
        "href",
    )

    for obj in objects:
        if not isinstance(obj, dict):
            continue

        for key in url_keys:
            yield obj.get(key)

        links = obj.get("links")
        if isinstance(links, dict):
            for key in url_keys:
                yield links.get(key)
            for value in links.values():
                if isinstance(value, str):
                    yield value
                elif isinstance(value, dict):
                    for key in url_keys:
                        yield value.get(key)

        if isinstance(links, list):
            for item in links:
                if isinstance(item, str):
                    yield item
                elif isinstance(item, dict):
                    for key in url_keys:
                        yield item.get(key)

        metadata = obj.get("metadata")
        if isinstance(metadata, dict):
            for key in url_keys:
                yield metadata.get(key)

        contexts = obj.get("contexts")
        if isinstance(contexts, dict):
            for context in contexts.values():
                if isinstance(context, dict):
                    for key in url_keys:
                        yield context.get(key)


def build_sentry_issue_url(organization_slug, issue_id):
    """Build a Sentry issue URL when webhook did not provide an explicit link."""
    if not organization_slug or not issue_id:
        return None

    return f"https://sentry.io/organizations/{organization_slug}/issues/{issue_id}/"


def sentry_url_from_payload(
    payload,
    data,
    issue,
    event,
    metric_alert,
    event_alert,
    alert_obj,
    organization_slug,
    issue_id,
):
    """Return the best available Sentry URL from known webhook payload shapes."""
    nested_url = first_event_link(
        *sentry_link_candidates(
            issue,
            event,
            metric_alert,
            event_alert,
            alert_obj,
            data,
            payload,
        )
    )

    if nested_url:
        return nested_url

    return first_event_link(
        # Issue payloads.
        issue.get("permalink"),
        issue.get("web_url"),
        issue.get("url"),
        issue.get("issue_url"),

        # Event payloads.
        event.get("web_url"),
        event.get("url"),
        event.get("event_url"),
        event.get("permalink"),

        # Metric/event alert payloads.
        metric_alert.get("web_url"),
        metric_alert.get("url"),
        metric_alert.get("alert_url"),
        metric_alert.get("issue_url"),
        event_alert.get("web_url"),
        event_alert.get("url"),
        event_alert.get("alert_url"),
        event_alert.get("issue_url"),
        alert_obj.get("web_url"),
        alert_obj.get("url"),
        alert_obj.get("alert_url"),
        alert_obj.get("issue_url"),

        # Data-level webhook fields.
        data.get("web_url"),
        data.get("url"),
        data.get("permalink"),
        data.get("issue_url"),
        data.get("event_url"),
        data.get("alert_url"),

        # Some webhook/proxy shapes put the URL at the top level.
        payload.get("web_url"),
        payload.get("url"),
        payload.get("permalink"),
        payload.get("issue_url"),
        payload.get("event_url"),
        payload.get("alert_url"),

        # Last-resort deterministic Sentry issue URL.
        build_sentry_issue_url(organization_slug, issue_id),
    )


def normalize_sentry(payload, headers=None):
    """Normalize Sentry Integration Platform webhooks."""
    headers = headers or {}
    data = payload.get("data") or {}
    action = str(payload.get("action") or "").lower()

    resource = (
        headers.get("Sentry-Hook-Resource")
        or headers.get("sentry-hook-resource")
        or data.get("resource")
        or "sentry"
    )
    resource = str(resource or "").lower()

    issue = data.get("issue") or data.get("group") or {}
    event = data.get("event") or {}
    metric_alert = data.get("metric_alert") or {}
    event_alert = data.get("event_alert") or {}

    alert_obj = metric_alert or event_alert or data.get("alert") or {}

    project_candidates = (
        data.get("project"),
        issue.get("project"),
        event.get("project"),
        alert_obj.get("project"),
    )

    project_id = None
    project_slug = None
    project_name = None

    for project_candidate in project_candidates:
        if project_id is None:
            project_id = normalize_sentry_integer_id(project_candidate)

        candidate_slug, candidate_name = normalize_sentry_named_object(project_candidate)

        if project_slug is None and candidate_slug:
            project_slug = candidate_slug

        if project_name is None and candidate_name:
            project_name = candidate_name

    organization = (
        data.get("organization")
        or payload.get("organization")
        or (payload.get("installation") or {}).get("organization")
        or {}
    )
    organization_slug, organization_name = normalize_sentry_named_object(organization)

    organization_slug = first_non_empty(
        organization_slug,
        data.get("organization_slug"),
        payload.get("organization_slug"),
        data.get("org_slug"),
        payload.get("org_slug"),
    )

    organization_name = first_non_empty(
        organization_name,
        data.get("organization_name"),
        payload.get("organization_name"),
        organization_slug,
    )

    issue_metadata = issue.get("metadata") or {}

    issue_id = first_non_empty(
        issue.get("id"),
        issue.get("issue_id"),
        data.get("issue_id"),
        event.get("issue_id"),
        event.get("groupID"),
        event.get("group_id"),
    )
    issue_short_id = first_non_empty(
        issue.get("shortId"),
        issue.get("short_id"),
        data.get("issue_short_id"),
    )
    event_id = first_non_empty(
        event.get("event_id"),
        event.get("id"),
        data.get("event_id"),
    )

    alert_id = first_non_empty(
        metric_alert.get("id"),
        event_alert.get("id"),
        alert_obj.get("id"),
        data.get("alert_id"),
    )

    is_metric_alert = resource == "metric_alert" or bool(metric_alert)

    if is_metric_alert:
        title = first_non_empty(
            metric_alert.get("title"),
            metric_alert.get("name"),
            data.get("title"),
            "Sentry metric alert",
        )

        message = first_non_empty(
            data.get("message"),
            metric_alert.get("description"),
            metric_alert.get("name"),
            "",
        )
    else:
        title = first_non_empty(
            issue.get("title"),
            event.get("title"),
            event.get("message"),
            data.get("title"),
            event_alert.get("title"),
            event_alert.get("name"),
            "Sentry alert",
        )

        message = first_non_empty(
            data.get("message"),
            event.get("message"),
            issue_metadata.get("value"),
            issue.get("culprit"),
            event.get("culprit"),
            "",
        )

    raw_level = first_non_empty(
        metric_alert.get("status"),
        metric_alert.get("level"),
        event.get("level"),
        issue.get("level"),
        data.get("level"),
        action,
        "error",
    )

    severity = normalize_sentry_severity(raw_level, action)
    status = normalize_sentry_status(resource, action, issue, metric_alert)

    sentry_url = sentry_url_from_payload(
        payload=payload,
        data=data,
        issue=issue,
        event=event,
        metric_alert=metric_alert,
        event_alert=event_alert,
        alert_obj=alert_obj,
        organization_slug=organization_slug,
        issue_id=issue_id,
    )

    if not sentry_url:
        logger.warning(
            "sentry webhook did not contain source event url",
            extra={
                "extra": {
                    "resource": resource,
                    "action": action,
                    "organization_slug": organization_slug,
                    "issue_id": issue_id,
                    "event_id": event_id,
                    "alert_id": alert_id,
                    "top_level_keys": sorted(payload.keys()),
                    "data_keys": sorted(data.keys()),
                    "issue_keys": sorted(issue.keys()),
                    "event_keys": sorted(event.keys()),
                    "metric_alert_keys": sorted(metric_alert.keys()),
                    "event_alert_keys": sorted(event_alert.keys()),
                }
            },
        )

    labels = {
        "alertname": normalize_sentry_alertname(resource, metric_alert),
        "severity": severity,
        "sentry_resource": resource,
        "sentry_action": action,
        "organization_slug": organization_slug,
        "organization_name": organization_name,
        "project_id": project_id,
        "project_slug": project_slug,
        "project_name": project_name,
        "issue_id": str(issue_id) if issue_id else None,
        "issue_short_id": issue_short_id,
        "event_id": event_id,
        "sentry_alert_id": str(alert_id) if alert_id else None,
        "sentry_alert_name": first_non_empty(
            metric_alert.get("name"),
            metric_alert.get("title"),
            event_alert.get("name"),
            event_alert.get("title"),
        ),
        "level": raw_level,
        "environment": first_non_empty(
            event.get("environment"),
            issue.get("environment"),
            data.get("environment"),
        ),
        "culprit": first_non_empty(issue.get("culprit"), event.get("culprit")),
        "sentry_url": sentry_url,
    }

    labels = {
        key: value
        for key, value in labels.items()
        if value not in (None, "")
    }

    sentry_tags = normalize_sentry_tags(
        payload.get("tags"),
        data.get("tags"),
        issue.get("tags"),
        event.get("tags"),
        metric_alert.get("tags"),
        event_alert.get("tags"),
        alert_obj.get("tags"),
    )

    for key, value in sentry_tags.items():
        labels.setdefault(key, value)

    add_event_link_label(labels, sentry_url)

    external_id = first_non_empty(
        issue_id,
        alert_id,
        event_id,
        title,
    )

    if issue_id:
        dedup_key = "sentry:issue:" + str(issue_id)
    elif resource == "metric_alert" and alert_id:
        dedup_key = "sentry:metric:" + str(alert_id)
    elif alert_id:
        dedup_key = "sentry:alert:" + str(alert_id)
    else:
        dedup_key = make_dedup_key("sentry", external_id, title, labels)

    return [
        {
            "source": "sentry",
            "team_slug": labels.get("team") or labels.get("oncall_team"),
            "external_id": str(external_id) if external_id else None,
            "dedup_key": dedup_key,
            "title": title,
            "message": message or "",
            "severity": severity,
            "labels": labels,
            "payload": payload,
            "status": status,
        }
    ]


def normalize_sentry_integer_id(value):
    """Return an integer ID from a Sentry project value."""
    if isinstance(value, dict):
        value = value.get("id")

    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, str) and value.isdigit():
        return int(value)

    return None


def normalize_sentry_named_object(value):
    if isinstance(value, str):
        return value, value

    if not isinstance(value, dict):
        return None, None

    slug = first_non_empty(value.get("slug"), value.get("name"))
    name = first_non_empty(value.get("name"), slug)

    return slug, name


def normalize_sentry_tags(*tag_sources):
    """Normalize Sentry tag formats into alert labels."""
    labels = {}

    for tags in tag_sources:
        if not tags:
            continue

        if isinstance(tags, dict):
            tag_items = tags.items()
        elif isinstance(tags, list):
            tag_items = iter_sentry_tag_list(tags)
        else:
            continue

        for key, value in tag_items:
            key = normalize_sentry_tag_key(key)
            value = normalize_sentry_tag_value(value)

            if key and value not in (None, ""):
                labels[key] = value

    return labels


def iter_sentry_tag_list(tags):
    """Yield key/value pairs from Sentry list-style tags."""
    for item in tags:
        if isinstance(item, dict):
            key = first_non_empty(
                item.get("key"),
                item.get("name"),
                item.get("tag"),
            )
            value = first_non_empty(
                item.get("value"),
                item.get("val"),
            )
            yield key, value
            continue

        if isinstance(item, (list, tuple)) and len(item) >= 2:
            yield item[0], item[1]


def normalize_sentry_tag_key(value):
    """Return a usable label key for a Sentry tag."""
    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    return value


def normalize_sentry_tag_value(value):
    """Return a usable label value for a Sentry tag."""
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()

        if not value:
            return None

        return value

    if isinstance(value, (int, float, bool)):
        return value

    return str(value)


def normalize_sentry_alertname(resource, metric_alert=None):
    if resource == "metric_alert" or metric_alert:
        return "SentryMetricAlert"

    if resource == "event_alert":
        return "SentryIssueAlert"

    if resource == "issue":
        return "SentryIssue"

    return "SentryAlert"


def normalize_sentry_severity(level, action=None):
    value = str(level or action or "").strip().lower()

    if value in {"fatal", "critical"}:
        return "critical"

    if value in {"error"}:
        return "critical"

    if value in {"warning", "warn"}:
        return "warning"

    if value in {"info", "debug", "resolved", "ok"}:
        return "info"

    return "warning"


def normalize_sentry_status(resource, action, issue=None, metric_alert=None):
    issue = issue or {}
    metric_alert = metric_alert or {}

    action = str(action or "").strip().lower()
    resource = str(resource or "").strip().lower()

    if resource == "metric_alert" and action in {"resolved", "ok"}:
        return "resolved"

    if resource == "issue" and action in {"resolved", "ignored", "archived"}:
        return "resolved"

    if action in {"resolved", "ignored", "archived", "closed", "ok"}:
        return "resolved"

    issue_status = str(issue.get("status") or "").strip().lower()
    if issue_status in {"resolved", "ignored", "closed"}:
        return "resolved"

    metric_status = str(metric_alert.get("status") or "").strip().lower()
    if metric_status in {"resolved", "ok", "closed"}:
        return "resolved"

    return "firing"
