"""The shared audit writer is usable in workers without Flask request context."""

import logging
from types import SimpleNamespace

import pytest

from app.services import audit as audit_service
from app.modules.redaction import REDACTED


def test_record_audit_accepts_explicit_user_and_token_without_request(
    monkeypatch, caplog,
):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=88)

    monkeypatch.setattr(audit_service.audit_repo, "create_audit_log", fake_create)

    with caplog.at_level(logging.INFO, logger="oncall.audit"):
        event = audit_service.record_audit(
            "maintenance_window.update",
            object_type="maintenance_window",
            object_id=25,
            group_id=3,
            team_id=4,
            user_id=11,
            api_token_id=9,
            transport="api",
            data={"password": "sensitive-value", "name": "maintenance"},
        )

    assert event.id == 88
    assert captured["user_id"] == 11
    assert captured["api_token_id"] == 9
    assert captured["data"]["transport"] == "api"
    assert captured["data"]["password"] == REDACTED
    assert captured["data"]["name"] == "maintenance"

    records = [
        record for record in caplog.records
        if record.name == "oncall.audit" and record.getMessage() == "user action"
    ]
    assert len(records) == 1
    assert records[0].extra["api_token_id"] == 9
    assert "sensitive-value" not in str(records[0].extra)


def test_record_audit_rejects_untrusted_transport_before_write(monkeypatch):
    calls = []
    monkeypatch.setattr(
        audit_service.audit_repo,
        "create_audit_log",
        lambda **kwargs: calls.append(kwargs),
    )
    with pytest.raises(ValueError, match="unsupported audit transport"):
        audit_service.record_audit("sample", transport="untrusted")

    assert calls == []
