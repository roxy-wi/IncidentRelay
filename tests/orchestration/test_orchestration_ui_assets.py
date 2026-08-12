import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_orchestration_catalogs_have_matching_keys():
    catalogs = []
    for locale in ("en", "ru", "de", "fr"):
        path = ROOT / "app" / "static" / "i18n" / locale / "orchestrations.json"
        catalogs.append(json.loads(path.read_text(encoding="utf-8")))

    assert set(catalogs[0]) == set(catalogs[1]) == set(catalogs[2]) == set(catalogs[3])
    assert "orchestrations.webhooks.private_network_policy" in catalogs[0]


def test_orchestration_page_is_registered_with_assets():
    index = (ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    routes = (ROOT / "app" / "views" / "pages_view.py").read_text(encoding="utf-8")
    state = (ROOT / "app" / "static" / "js" / "core" / "state.js").read_text(encoding="utf-8")

    assert 'pages/orchestrations.html' in index
    assert 'js/pages/orchestrations.js' in index
    assert 'css/orchestrations.css' in index
    assert '@pages_bp.route("/event-orchestration")' in routes
    assert '"/event-orchestration"' in state


def test_orchestration_ui_uses_shared_catalog_and_safe_api_surfaces():
    javascript = (
        ROOT / "app" / "static" / "js" / "pages" / "orchestrations.js"
    ).read_text(encoding="utf-8")
    template = (
        ROOT / "app" / "templates" / "pages" / "orchestrations.html"
    ).read_text(encoding="utf-8")

    assert "/api/event-orchestrations/catalog" in javascript
    assert "/api/orchestration-webhook-actions" in javascript
    assert "orchestration-field-options" in javascript
    assert 'id="orchestration-field-options"' in template
    assert 'id="orchestration-webhook-private-policy"' in template


def test_orchestration_ui_uses_shared_json_formatter_and_explicit_builder_toggle():
    javascript = (
        ROOT / "app" / "static" / "js" / "pages" / "orchestrations.js"
    ).read_text(encoding="utf-8")
    template = (
        ROOT / "app" / "templates" / "pages" / "orchestrations.html"
    ).read_text(encoding="utf-8")

    assert 'formatJsonTextarea(' in javascript
    assert '"#orchestration-definition-json"' in javascript
    assert 'id="orchestration-format-json"' in template
    assert 'id="orchestration-back-to-builder"' in template
    assert 'orchestrations.actions.builder_view' in template


def test_orchestration_ui_supports_deep_links_and_stable_webhook_layout():
    javascript = (
        ROOT / "app" / "static" / "js" / "pages" / "orchestrations.js"
    ).read_text(encoding="utf-8")
    template = (
        ROOT / "app" / "templates" / "pages" / "orchestrations.html"
    ).read_text(encoding="utf-8")
    stylesheet = (
        ROOT / "app" / "static" / "css" / "orchestrations.css"
    ).read_text(encoding="utf-8")

    assert 'params.get("orchestration_id")' in javascript
    assert 'url.searchParams.set("orchestration_id"' in javascript
    assert '$(window).on("popstate"' in javascript
    assert 'class="orchestration-webhook-grid"' in template
    assert 'id="orchestration-webhook-format-headers"' in template
    assert '.orchestration-webhook-grid' in stylesheet


def test_orchestration_list_supports_editing_links_and_shared_action_menu():
    javascript = (
        ROOT / "app" / "static" / "js" / "pages" / "orchestrations.js"
    ).read_text(encoding="utf-8")
    template = (
        ROOT / "app" / "templates" / "pages" / "orchestrations.html"
    ).read_text(encoding="utf-8")

    assert "renderOrchestrationActions" in javascript
    assert "window.makeActionMenu" in javascript
    assert "openOrchestrationEditModal" in javascript
    assert 'url.searchParams.set("orchestration_id"' in javascript
    assert 'id="orchestration-create-modal-title"' in template
    assert 'id="orchestration-settings-scope"' in template
    assert 'id="orchestration-settings-service"' in template
