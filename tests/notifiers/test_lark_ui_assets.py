import json
from pathlib import Path

from app.i18n import SUPPORTED_LOCALES


ROOT = Path(__file__).resolve().parents[2]


def test_lark_channel_catalog_keys_exist_in_every_locale():
    required = {
        "channels.type.lark",
        "channels.lark.webhook_url",
        "channels.lark.signing_secret",
        "channels.lark.signing_secret_help",
        "channels.lark.help",
    }

    for locale in SUPPORTED_LOCALES:
        path = ROOT / "app" / "static" / "i18n" / locale / "channels.json"
        catalog = json.loads(path.read_text(encoding="utf-8"))
        assert required <= set(catalog), locale
        assert all(catalog[key].strip() for key in required), locale


def test_lark_channel_fields_are_wired_to_the_form():
    template = (
        ROOT / "app" / "templates" / "pages" / "channels.html"
    ).read_text(encoding="utf-8")
    javascript = (
        ROOT / "app" / "static" / "js" / "pages" / "channels.js"
    ).read_text(encoding="utf-8")

    assert 'data-channel-config="lark"' in template
    assert 'id="cfg-lark-webhook-url"' in template
    assert 'id="cfg-lark-signing-secret"' in template
    assert 'lark: "channels.type.lark"' in javascript
    assert '[data-channel-config="lark"]' in javascript
