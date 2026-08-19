from datetime import datetime
from pathlib import Path


from app.api.schemas.silences import SilenceCreateSchema
from app.modules.db import silences_repo
from app.modules.db.models import Silence
from tests.factories import create_group, create_silence, create_team, unique


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _silence_payload(team_id: int) -> dict[str, object]:
    return {
        "team_id": team_id,
        "name": "Timezone test",
        "reason": "Verify UTC conversion",
        "matchers": {"labels": {"service": "database"}},
        "starts_at": "2026-07-30T10:15:00+03:00",
        "ends_at": "2026-07-30T11:15:00+03:00",
    }


def test_silence_schema_normalizes_offset_timestamps_to_naive_utc():
    payload = SilenceCreateSchema(**_silence_payload(1))

    assert payload.starts_at == datetime(2026, 7, 30, 7, 15)
    assert payload.ends_at == datetime(2026, 7, 30, 8, 15)
    assert payload.starts_at.tzinfo is None
    assert payload.ends_at.tzinfo is None


def test_silence_schema_treats_offset_free_timestamps_as_utc():
    payload = SilenceCreateSchema(
        **{
            **_silence_payload(1),
            "starts_at": "2026-07-30T07:15:00",
            "ends_at": "2026-07-30T08:15:00",
        }
    )

    assert payload.starts_at == datetime(2026, 7, 30, 7, 15)
    assert payload.ends_at == datetime(2026, 7, 30, 8, 15)


def test_silence_api_stores_utc_and_serializes_explicit_z(
    client,
    admin_headers,
    db,
):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))

    response = client.post(
        "/api/silences",
        headers=admin_headers,
        json=_silence_payload(team.id),
    )

    assert response.status_code == 201, response.get_json()

    payload = response.get_json()
    silence = Silence.get_by_id(payload["id"])

    assert silence.starts_at == datetime(2026, 7, 30, 7, 15)
    assert silence.ends_at == datetime(2026, 7, 30, 8, 15)
    assert payload["starts_at"] == "2026-07-30T07:15:00Z"
    assert payload["ends_at"] == "2026-07-30T08:15:00Z"


def test_silence_end_boundary_is_exclusive(db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    boundary = datetime(2026, 7, 30, 8, 15)

    silence = create_silence(
        team,
        starts_at=datetime(2026, 7, 30, 7, 15),
        ends_at=boundary,
    )

    assert silences_repo.list_active_silences(
        team.id,
        now=datetime(2026, 7, 30, 8, 14, 59),
    ) == [silence]
    assert silences_repo.list_active_silences(team.id, now=boundary) == []


def test_silence_ui_uses_utc_conversion_helpers_and_matching_boundary():
    dates_source = (
        PROJECT_ROOT / "app/static/js/core/dates.js"
    ).read_text(encoding="utf-8")
    silence_source = (
        PROJECT_ROOT / "app/static/js/pages/silences.js"
    ).read_text(encoding="utf-8")

    assert "function datetimeLocalToUtcIso(value)" in dates_source
    assert "return date.toISOString();" in dates_source
    assert "function utcIsoToDatetimeLocal(value)" in dates_source
    assert "datetimeLocalToUtcIso($(\"#silence-starts-at\").val())" in silence_source
    assert "utcIsoToDatetimeLocal(silence.starts_at)" in silence_source
    assert "endsAt && now >= endsAt" in silence_source
