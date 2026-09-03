import json
import re
from pathlib import Path

from app.i18n import SUPPORTED_LOCALES


ROOT = Path(__file__).resolve().parents[1]
CATALOG_ROOT = ROOT / "app" / "static" / "i18n"
PLACEHOLDER_RE = re.compile(r"\{[A-Za-z0-9_]+\}")


def load_catalog_file(locale, filename):
    return json.loads(
        (CATALOG_ROOT / locale / filename).read_text(encoding="utf-8")
    )


def test_spanish_locale_is_registered():
    assert SUPPORTED_LOCALES["es"] == "Español"


def test_spanish_catalog_files_and_keys_match_english():
    english_files = sorted(
        path.name for path in (CATALOG_ROOT / "en").glob("*.json")
    )
    spanish_files = sorted(
        path.name for path in (CATALOG_ROOT / "es").glob("*.json")
    )

    assert spanish_files == english_files

    for filename in english_files:
        english = load_catalog_file("en", filename)
        spanish = load_catalog_file("es", filename)

        assert set(spanish) == set(english), filename


def test_spanish_catalog_preserves_format_placeholders():
    for path in sorted((CATALOG_ROOT / "en").glob("*.json")):
        english = load_catalog_file("en", path.name)
        spanish = load_catalog_file("es", path.name)

        for key, english_value in english.items():
            assert sorted(PLACEHOLDER_RE.findall(spanish[key])) == sorted(
                PLACEHOLDER_RE.findall(english_value)
            ), key


def test_calendar_and_services_runtime_support_spanish_locale():
    calendar = (
        ROOT / "app" / "static" / "js" / "pages" / "calendar.js"
    ).read_text(encoding="utf-8")
    services_runtime = (
        ROOT / "app" / "static" / "js" / "pages" / "services" / "i18n_runtime.js"
    ).read_text(encoding="utf-8")

    assert 'es: "es-ES"' in calendar
    assert 'const numberedSpanish = [' in services_runtime
    assert 'i18n.locale === "es"' in services_runtime
    assert 'return "Presupuesto usado: " + match[1];' in services_runtime
