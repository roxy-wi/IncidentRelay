from pathlib import Path

import pytest
from flask import Flask, render_template_string

from app.i18n import (
    DEFAULT_LOCALE,
    get_current_locale,
    normalize_locale,
    register_i18n,
)


ROOT = Path(__file__).resolve().parents[2]


def create_test_app():
    app = Flask(
        __name__,
        static_folder=str(ROOT / "app" / "static"),
    )
    register_i18n(app)

    @app.get("/")
    def index():
        return render_template_string(
            "{{ _('login.submit') }}|{{ current_locale }}"
        )

    return app


def test_normalize_locale_accepts_region_variants():
    assert normalize_locale("ru-RU") == "ru"
    assert normalize_locale("en_US") == "en"
    assert normalize_locale("de-DE") == "de"
    assert normalize_locale("fr-FR") == "fr"
    assert normalize_locale("es-ES") == "es"
    assert normalize_locale("zh-ZH") == "zh"


def test_normalize_locale_rejects_unsupported_values():
    assert normalize_locale("it") is None
    assert normalize_locale("../../ru") is None


def test_cookie_locale_has_priority_over_accept_language():
    app = create_test_app()

    with app.test_request_context(
        "/",
        headers={
            "Cookie": "incidentrelay_locale=ru",
            "Accept-Language": "en",
        },
    ):
        assert get_current_locale() == "ru"


def test_accept_language_selects_supported_locale():
    app = create_test_app()
    response = app.test_client().get(
        "/",
        headers={"Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"},
    )

    assert response.get_data(as_text=True) == "Войти|ru"


def test_accept_language_selects_german_locale():
    app = create_test_app()
    response = app.test_client().get(
        "/",
        headers={"Accept-Language": "de-DE,de;q=0.9,en;q=0.8"},
    )

    assert response.get_data(as_text=True) == "Anmelden|de"


def test_accept_language_selects_french_locale():
    app = create_test_app()
    response = app.test_client().get(
        "/",
        headers={"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"},
    )

    assert response.get_data(as_text=True) == "Se connecter|fr"


def test_unsupported_language_falls_back_to_english():
    app = create_test_app()

    with app.test_request_context(
        "/",
        headers={"Accept-Language": "it-IT,pt-BR;q=0.9"},
    ):
        assert get_current_locale() == DEFAULT_LOCALE


def test_authenticated_user_locale_has_priority_over_cookie():
    from types import SimpleNamespace

    from flask import request

    app = create_test_app()

    with app.test_request_context(
        "/",
        headers={
            "Cookie": "incidentrelay_locale=en",
            "Accept-Language": "en",
        },
    ):
        request.current_user = SimpleNamespace(locale="de")
        assert get_current_locale() == "de"


@pytest.mark.parametrize(
    "locale, title, deployment, pagination",
    [
        ("en", "Changes", "Deployment", "Page 2 of 3 · 51 entries"),
        ("de", "Änderungen", "Deployment", "Seite 2 von 3 · 51 Einträge"),
        ("fr", "Changements", "Déploiement", "Page 2 sur 3 · 51 entrées"),
        ("es", "Cambios", "Despliegue", "Página 2 de 3 · 51 entradas"),
        ("ru", "Изменения", "Деплой", "Страница 2 из 3 · записей: 51"),
        ("zh", "变更", "部署", "第 2 页，共 3 页 · 51 条记录"),
    ],
)
def test_changes_messages_render_in_selected_locale(
    locale, title, deployment, pagination
):
    """Load Changes labels and format pagination without English fallback."""
    app = create_test_app()
    with app.test_request_context(
        "/", headers={"Cookie": f"incidentrelay_locale={locale}"}
    ):
        rendered = render_template_string(
            "{{ _('changes.title') }}|{{ _('changes.deployment') }}|"
            "{{ _('changes.pagination', page=2, pages=3, count=51) }}"
        )

    assert rendered == f"{title}|{deployment}|{pagination}"
