from app.services import scheduler


class _FakeDb:
    def __init__(self):
        self.closed = True
        self.connect_calls = 0
        self.close_calls = 0

    def is_closed(self):
        return self.closed

    def connect(self, reuse_if_open=False):
        self.closed = False
        self.connect_calls += 1

    def close(self):
        self.closed = True
        self.close_calls += 1


def test_retention_cleanup_job_runs_all_cleanup_under_one_lock(monkeypatch):
    fake_db = _FakeDb()
    calls = []

    monkeypatch.setattr(scheduler, "db", fake_db)
    monkeypatch.setattr(scheduler.Config, "RETENTION_ALERT_DAYS", 90)
    monkeypatch.setattr(scheduler.Config, "RETENTION_EXPLAIN_TRACE_DAYS", 30)
    monkeypatch.setattr(
        scheduler.Config,
        "RETENTION_ORCHESTRATION_EXECUTION_DAYS",
        14,
    )
    monkeypatch.setattr(scheduler.Config, "RETENTION_BATCH_SIZE", 250)
    monkeypatch.setattr(
        scheduler,
        "acquire_db_lock",
        lambda name: calls.append(("lock", name)) or "owner",
    )
    monkeypatch.setattr(
        scheduler,
        "release_db_lock",
        lambda name, owner: calls.append(("unlock", name, owner)),
    )
    monkeypatch.setattr(
        scheduler,
        "cleanup_alert_history",
        lambda **kwargs: calls.append(("alerts", kwargs)) or {
            "groups_deleted": 2,
            "alerts_deleted": 3,
        },
    )
    monkeypatch.setattr(
        scheduler,
        "cleanup_alert_explain_traces",
        lambda **kwargs: calls.append(("explain", kwargs)) or {
            "traces_deleted": 4,
            "steps_deleted": 8,
        },
    )
    monkeypatch.setattr(
        scheduler,
        "cleanup_orchestration_retention",
        lambda **kwargs: calls.append(("orchestration", kwargs)) or {
            "executions_deleted": 5,
            "pending_events_deleted": 6,
            "webhook_executions_deleted": 7,
        },
    )

    result = scheduler.retention_cleanup_job()

    assert result["alert_history"]["groups_deleted"] == 2
    assert result["explain_traces"]["traces_deleted"] == 4
    assert result["orchestration"]["executions_deleted"] == 5
    assert ("alerts", {"retention_days": 90, "batch_size": 250}) in calls
    assert ("explain", {"retention_days": 30}) in calls
    assert (
        "orchestration",
        {"execution_retention_days": 14},
    ) in calls
    assert calls[0] == ("lock", "retention_cleanup_job")
    assert calls[-1] == ("unlock", "retention_cleanup_job", "owner")
    assert fake_db.connect_calls == 1
    assert fake_db.close_calls == 1


def test_retention_cleanup_job_skips_when_lock_is_busy(monkeypatch):
    fake_db = _FakeDb()

    monkeypatch.setattr(scheduler, "db", fake_db)
    monkeypatch.setattr(scheduler, "acquire_db_lock", lambda _name: None)
    monkeypatch.setattr(
        scheduler,
        "cleanup_alert_history",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    result = scheduler.retention_cleanup_job()

    assert result["skipped"] is True
    assert fake_db.connect_calls == 1
    assert fake_db.close_calls == 1
