"""Deterministically rebuild operation state from immutable accepted events."""

TERMINAL_TYPES = {
    "change.succeeded",
    "change.failed",
    "change.rolled_back",
    "change.cancelled",
}
PROJECTION_FIELDS = ("title", "description", "external_url")


def project_events(events, ordering_mode, fallback_title):
    """Delivery order never selects the outcome or a metadata winner."""

    def order(event):
        return (
            event.source_sequence if ordering_mode == "sequence" else event.occurred_at
        )

    values = {
        "title": fallback_title,
        "description": None,
        "external_url": None,
        "status": "unknown",
        "lifecycle_conflict": False,
        "completed_at": None,
        "diagnostics": [],
        "first_occurred_at": min(event.occurred_at for event in events),
        "last_occurred_at": max(event.occurred_at for event in events),
    }
    ordered = sorted(events, key=lambda event: (order(event), event.external_event_id))
    starts = [
        event.occurred_at for event in events if event.event_type == "change.started"
    ]
    values["started_at"] = min(starts) if starts else None
    if starts:
        values["status"] = "running"
    for event in ordered:
        for name in PROJECTION_FIELDS:
            if name in event.projection_fields:
                values[name] = event.projection_fields[name]
    terminals = [event for event in ordered if event.event_type in TERMINAL_TYPES]
    if terminals:
        latest = [event for event in terminals if order(event) == order(terminals[-1])]
        if len({event.event_type for event in latest}) > 1:
            values.update(status="unknown", lifecycle_conflict=True)
            values["diagnostics"].append(
                {
                    "code": "terminal_conflict",
                    "event_ids": [event.external_event_id for event in latest[:20]],
                    "count": len(latest),
                }
            )
        else:
            values["status"] = latest[-1].event_type.removeprefix("change.")
            values["completed_at"] = latest[-1].occurred_at
    if (
        values["started_at"]
        and values["completed_at"]
        and values["completed_at"] < values["started_at"]
    ):
        values["diagnostics"].append({"code": "completion_before_start"})
    if ordering_mode == "sequence" and any(
        following.occurred_at < previous.occurred_at
        for previous, following in zip(ordered, ordered[1:], strict=False)
    ):
        values["diagnostics"].append({"code": "sequence_time_inversion"})
    return values
