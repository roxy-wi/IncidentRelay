"""Incident Stakeholder ownership and API contract, final 2.5 schema."""
from app.modules.db.models import IncidentStakeholder

def test_incident_stakeholder_is_canonical():
    assert "incident" in IncidentStakeholder._meta.fields
    assert IncidentStakeholder._meta.fields["incident"].rel_model.__name__ == "Incident"
    assert "group" not in IncidentStakeholder._meta.fields

def test_incident_stakeholder_routes():
    from app.views.incidents_view import (
        list_operational_stakeholders, add_operational_stakeholder,
        remove_operational_stakeholder)
    assert all(callable(handler) for handler in (
        list_operational_stakeholders, add_operational_stakeholder,
        remove_operational_stakeholder))
