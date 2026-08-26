from pathlib import Path

from app.modules.db.models import User


def test_profile_updates_locale_and_theme(client, auth_headers, admin_user):
    response = client.put(
        "/api/profile",
        json={
            "locale": "ru-RU",
            "theme": "dark",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["locale"] == "ru"
    assert data["theme"] == "dark"

    stored_user = User.get_by_id(admin_user.id)
    assert stored_user.locale == "ru"
    assert stored_user.theme == "dark"


def test_profile_rejects_unsupported_locale_and_theme(client, auth_headers):
    locale_response = client.put(
        "/api/profile",
        json={"locale": "es"},
        headers=auth_headers,
    )
    theme_response = client.put(
        "/api/profile",
        json={"theme": "midnight"},
        headers=auth_headers,
    )

    assert locale_response.status_code == 400
    assert theme_response.status_code == 400


def test_authenticated_shell_uses_profile_preferences(
    client,
    auth_headers,
    admin_user,
):
    admin_user.locale = "ru"
    admin_user.theme = "dark"
    admin_user.save()

    response = client.get("/profile", headers=auth_headers)

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '<html lang="ru" data-theme="dark">' in html
    assert 'id="global-language-filter"' not in html
    assert 'id="profile-language"' in html
    assert 'id="profile-theme"' in html
    assert 'class="form-body profile-interface-fields"' in html
    assert '/static/css/theme_dark.css' in html
    assert 'js/core/theme.js' in html


def test_dark_theme_overrides_shared_light_surfaces():
    css = Path("app/static/css/theme_dark.css").read_text(encoding="utf-8")

    assert ".app-modal-header" in css
    assert ".app-modal-footer" in css
    assert ".table-pagination" in css
    assert ".alerts-pagination" in css
    assert ".orchestration-rule-card" in css
    assert "--card-background: #111827" in css
    assert "--border-color: #334155" in css
    assert "--surface-elevated: var(--md-surface-soft)" in css
    assert "--surface-color: var(--md-surface)" in css
    assert ".detail-item" in css
    assert ".event-item" in css
    assert ".stack-card-header" in css
    assert ".alert-service-context" in css
    assert ".impact-path-node" in css
