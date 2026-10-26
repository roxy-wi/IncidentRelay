"""Static final 2.5 ownership gates independent of external database fixtures."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_canonical_models_only():
    models = (ROOT / "app/modules/db/models.py").read_text(encoding="utf-8")
    for unused in ("class IncidentParticipant(", "class IncidentOperationalStakeholder("):
        assert unused not in models
    for cls in ("IncidentResponder", "IncidentStakeholder"):
        chunk = models.split(f"class {cls}(BaseModel):", 1)[1].split("class ", 1)[0]
        assert "incident = ForeignKeyField(Incident" in chunk
        assert "group = ForeignKeyField(" not in chunk


def test_no_intermediate_migrations():
    migrations = ROOT / "app/migrations"
    assert not (migrations / "20261025010000_incident_participants.py").exists()
    assert not (migrations / "20261025020000_incident_operational_stakeholders.py").exists()


def test_legacy_alert_group_collaboration_api_removed():
    api = (ROOT / "app/views/alerts_view.py").read_text(encoding="utf-8")
    assert '@alerts_bp.route("/<int:alert_id>/responders"' not in api
    assert '@alerts_bp.route("/<int:alert_id>/stakeholders"' not in api
