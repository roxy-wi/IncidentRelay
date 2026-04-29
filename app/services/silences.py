from app.modules.db import silences_repo
from app.services.matchers import match_alert


def find_active_silence(team_id, alert_data):
    """
    Return the first active silence matching an alert.
    """

    if not team_id:
        return None

    for silence in silences_repo.list_active_silences(team_id):
        if match_alert(alert_data, silence.matchers or {}):
            return silence
    return None
