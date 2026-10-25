"""Dashboard Active Alerts filter controls render in the SPA shell.

The dashboard filters live inside the Active Alerts card (a My/All scope toggle
plus a collapsible advanced-filters panel). The earlier dashboard-wide filter
card and the duplicate team filter were removed in favour of the global top-bar
team selector.
"""


def test_dashboard_renders_active_alerts_filter_controls(client, admin_headers):
    resp = client.get("/", headers=admin_headers)

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    for present in [
        'id="dashboard-scope-mine"',
        'id="dashboard-scope-all"',
        'id="dashboard-filters-toggle"',
        'id="dashboard-filters-panel"',
        'id="dashboard-involvement-filter"',
        'id="dashboard-service-filter"',
        'id="dashboard-filters-reset"',
    ]:
        assert present in html, present


def test_dashboard_drops_legacy_filter_card_and_team_filter(client, admin_headers):
    resp = client.get("/", headers=admin_headers)

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    for gone in [
        "dashboard-filters-card",
        'id="dashboard-team-filter"',
        'id="dashboard-my-teams"',
    ]:
        assert gone not in html, gone
