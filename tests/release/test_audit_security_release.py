from __future__ import annotations

import logging
from types import SimpleNamespace

import app.services.audit as audit_service
from app.modules.redaction import REDACTED


def test_audit_persists_redacted_details_but_does_not_copy_them_to_app_log(
    app,
    monkeypatch,
    caplog,
):
    captured = {}

    def fake_create_audit_log(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=41)

    monkeypatch.setattr(
        audit_service.audit_repo,
        "create_audit_log",
        fake_create_audit_log,
    )

    with app.test_request_context("/_release/audit", method="POST"):
        with caplog.at_level(logging.INFO, logger="oncall.audit"):
            entry = audit_service.write_audit(
                action="integration.updated",
                object_type="integration",
                object_id=17,
                message=(
                    "Updated integration with "
                    "password=release-secret&token=release-token"
                ),
                data={
                    "password": "release-secret",
                    "api_token": "release-token",
                    "nested": {
                        "authorization": "Bearer release-bearer",
                    },
                    "non_sensitive": "visible-value",
                },
            )

    assert entry.id == 41

    # The database audit record keeps useful details, but secrets are redacted.
    assert "release-secret" not in str(captured)
    assert "release-token" not in str(captured)
    assert "release-bearer" not in str(captured)
    assert REDACTED in str(captured)
    assert captured["data"]["non_sensitive"] == "visible-value"

    records = [
        record
        for record in caplog.records
        if record.name == "oncall.audit"
        and record.getMessage() == "user action"
    ]
    assert len(records) == 1

    structured = records[0].extra

    # Application logs contain identifiers only. Detailed audit message/data
    # belong in the audit table and must not be duplicated into log streams.
    assert structured["event_type"] == "user_action"
    assert structured["audit_id"] == 41
    assert structured["action"] == "integration.updated"
    assert structured["object_type"] == "integration"
    assert structured["object_id"] == 17
    assert "message" not in structured
    assert "data" not in structured

    serialized_log = str(structured)
    assert "release-secret" not in serialized_log
    assert "release-token" not in serialized_log
    assert "release-bearer" not in serialized_log
    assert "visible-value" not in serialized_log


def test_audit_uses_current_request_identity_without_logging_sensitive_data(
    app,
    monkeypatch,
    caplog,
):
    captured = {}

    def fake_create_audit_log(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=42)

    monkeypatch.setattr(
        audit_service.audit_repo,
        "create_audit_log",
        fake_create_audit_log,
    )

    with app.test_request_context("/_release/audit", method="POST"):
        audit_service.request.current_user = SimpleNamespace(id=7)
        audit_service.request.current_api_token = SimpleNamespace(id=9)

        with caplog.at_level(logging.INFO, logger="oncall.audit"):
            audit_service.write_audit(
                action="token.rotated",
                message="new secret=do-not-log-this",
                data={"private_key": "private-material"},
            )

    assert captured["user_id"] == 7
    assert captured["api_token_id"] == 9
    assert "do-not-log-this" not in str(captured)
    assert "private-material" not in str(captured)

    record = next(
        record
        for record in caplog.records
        if record.name == "oncall.audit"
        and record.getMessage() == "user action"
    )
    assert record.extra["user_id"] == 7
    assert record.extra["api_token_id"] == 9
    assert "message" not in record.extra
    assert "data" not in record.extra
