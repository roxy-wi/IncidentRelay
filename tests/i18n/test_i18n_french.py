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


def test_french_locale_is_registered():
    assert SUPPORTED_LOCALES["fr"] == "Français"


def test_french_catalog_files_and_keys_match_english():
    english_files = sorted(path.name for path in (CATALOG_ROOT / "en").glob("*.json"))
    french_files = sorted(path.name for path in (CATALOG_ROOT / "fr").glob("*.json"))

    assert french_files == english_files

    for filename in english_files:
        english = load_catalog_file("en", filename)
        french = load_catalog_file("fr", filename)

        assert set(french) == set(english), filename


def test_french_catalog_preserves_format_placeholders():
    for path in sorted((CATALOG_ROOT / "en").glob("*.json")):
        english = load_catalog_file("en", path.name)
        french = load_catalog_file("fr", path.name)

        for key, english_value in english.items():
            assert sorted(PLACEHOLDER_RE.findall(french[key])) == sorted(
                PLACEHOLDER_RE.findall(english_value)
            ), key


def test_services_runtime_contains_french_dynamic_translations():
    script = (
        ROOT / "app" / "static" / "js" / "pages" / "services" / "i18n_runtime.js"
    ).read_text(encoding="utf-8")

    assert 'i18n.locale === "fr"' in script
    assert 'const numberedFrench = [' in script
    assert 'return "Budget utilisé : " + match[1];' in script
