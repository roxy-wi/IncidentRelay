from app.services import scheduler


def test_user_notification_rules_job_processes_due_deliveries(db, monkeypatch):
    calls = []

    monkeypatch.setattr(
        scheduler,
        "acquire_db_lock",
        lambda name: "test-owner",
    )
    monkeypatch.setattr(
        scheduler,
        "release_db_lock",
        lambda name, owner: calls.append(("release", name, owner)),
    )
    monkeypatch.setattr(
        scheduler,
        "process_due_user_notifications",
        lambda: 3,
    )

    result = scheduler.user_notification_rules_job()

    assert result == 3
    assert calls == [
        ("release", "user_notification_rules_job", "test-owner"),
    ]


def test_user_notification_rules_job_skips_when_lock_is_busy(db, monkeypatch):
    monkeypatch.setattr(
        scheduler,
        "acquire_db_lock",
        lambda name: None,
    )
    monkeypatch.setattr(
        scheduler,
        "process_due_user_notifications",
        lambda: (_ for _ in ()).throw(
            AssertionError("must not process without lock")
        ),
    )

    assert scheduler.user_notification_rules_job() == 0
