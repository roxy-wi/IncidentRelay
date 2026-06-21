from datetime import datetime, timedelta

from app.services.oncall_health import HealthIssue, merge_schedule_gap_issues, summarize_issues


def test_summarize_issues_returns_ok_when_only_info():
    summary = summarize_issues([
        HealthIssue(
            severity="info",
            code="informational_issue",
            title="Informational issue",
            message="Informational message",
            target_type="test",
        )
    ])

    assert summary["status"] == "ok"
    assert summary["critical"] == 0
    assert summary["warning"] == 0
    assert summary["info"] == 1


def test_summarize_issues_prefers_critical_over_warning():
    summary = summarize_issues([
        HealthIssue(
            severity="warning",
            code="single_member",
            title="Single member",
            message="Only one member.",
            target_type="rotation",
        ),
        HealthIssue(
            severity="critical",
            code="no_current_oncall",
            title="No on-call",
            message="No current on-call user.",
            target_type="rotation",
        ),
    ])

    assert summary["status"] == "critical"
    assert summary["critical"] == 1
    assert summary["warning"] == 1


def test_merge_schedule_gap_issues_merges_touching_ranges():
    start = datetime(2026, 1, 1, 0, 0, 0)
    first = HealthIssue(
        severity="critical",
        code="schedule_gap",
        title="Schedule gap",
        message="No user.",
        target_type="rotation",
        starts_at=start,
        ends_at=start + timedelta(minutes=15),
    )
    second = HealthIssue(
        severity="critical",
        code="schedule_gap",
        title="Schedule gap",
        message="No user.",
        target_type="rotation",
        starts_at=start + timedelta(minutes=15),
        ends_at=start + timedelta(minutes=30),
    )

    merged = merge_schedule_gap_issues([first, second])

    assert len(merged) == 1
    assert merged[0].starts_at == start
    assert merged[0].ends_at == start + timedelta(minutes=30)
