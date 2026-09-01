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


def test_dark_theme_uses_shared_material_tokens():
    material_css = Path("app/static/css/material.css").read_text(encoding="utf-8")
    dark_css = Path("app/static/css/theme_dark.css").read_text(encoding="utf-8")

    assert "--surface: var(--md-surface)" in material_css
    assert "--text: var(--md-text)" in material_css
    assert "--card-background: var(--md-surface)" in material_css
    assert "--md-surface: #111827" in dark_css
    assert "--md-input-bg: #0f172a" in dark_css
    assert "--md-code-bg: #020617" in dark_css

    # First-party page components consume shared tokens instead of being
    # re-declared one-by-one in the dark stylesheet.
    assert ".detail-item" not in dark_css
    assert ".event-item" not in dark_css
    assert ".alert-service-context" not in dark_css
    assert ".impact-path-node" not in dark_css
