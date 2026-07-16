from pathlib import Path

from flask import Flask, render_template_string

from app.i18n import (
    DEFAULT_LOCALE,
    get_current_locale,
    normalize_locale,
    register_i18n,
)


ROOT = Path(__file__).resolve().parents[1]


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


def test_normalize_locale_rejects_unsupported_values():
    assert normalize_locale("fr") is None
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


def test_unsupported_language_falls_back_to_english():
    app = create_test_app()

    with app.test_request_context(
        "/",
        headers={"Accept-Language": "fr-FR,fr;q=0.9"},
    ):
        assert get_current_locale() == DEFAULT_LOCALE
