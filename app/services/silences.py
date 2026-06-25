from app.modules.db import silences_repo
from app.services.routing.matcher.match_context import alert_rule_matches


def find_active_silence(team_id, alert_data):
    """Return the first active silence matching an alert."""
    if not team_id:
        return None

    for silence in silences_repo.list_active_silences(team_id):
        if alert_rule_matches(
            alert_data,
            silence,
            team=silence.team,
        ):
            return silence

    return None
