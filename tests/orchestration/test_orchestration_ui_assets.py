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


def test_orchestration_action_editor_has_localized_column_help():
    javascript = (
        ROOT / "app" / "static" / "js" / "pages" / "orchestrations.js"
    ).read_text(encoding="utf-8")

    expected_keys = {
        "orchestrations.rule_editor.action_type",
        "orchestrations.rule_editor.action_type_help",
        "orchestrations.rule_editor.parameters",
        "orchestrations.rule_editor.parameters_help",
        "orchestrations.rule_editor.on_failure",
        "orchestrations.rule_editor.on_failure_help",
        "orchestrations.rule_editor.failure_continue",
        "orchestrations.rule_editor.failure_stop_rule",
        "orchestrations.rule_editor.failure_stop_orchestration",
        "orchestrations.rule_editor.remove_action",
    }

    for locale in ("en", "ru", "de", "fr"):
        path = ROOT / "app" / "static" / "i18n" / locale / "orchestrations.json"
        catalog = json.loads(path.read_text(encoding="utf-8"))
        assert expected_keys <= set(catalog)
        assert all(catalog[key].strip() for key in expected_keys)

    assert "orchestrationActionEditorHeader" in javascript
    assert "orchestrationActionFailureEditor" in javascript
    assert "orchestration-action-editor-header" in javascript
    assert 'i18n.t("orchestrations.rule_editor.action_type_help")' in javascript
    assert 'i18n.t("orchestrations.rule_editor.on_failure_help")' in javascript
    assert 'i18n.t("orchestrations.rule_editor.failure_stop_orchestration")' in javascript



def test_orchestration_condition_editor_has_localized_column_help_and_operator_labels():
    javascript = (
        ROOT / "app" / "static" / "js" / "pages" / "orchestrations.js"
    ).read_text(encoding="utf-8")

    operator_keys = {
        "orchestrations.rule_editor.operator_" + operator
        for operator in (
            "equals", "not_equals", "contains", "not_contains", "starts_with",
            "ends_with", "regex", "not_regex", "in", "not_in", "exists",
            "not_exists", "greater_than", "less_than", "greater_or_equal",
            "less_or_equal", "is_true", "is_false",
        )
    }
    expected_keys = operator_keys | {
        "orchestrations.rule_editor.condition_field",
        "orchestrations.rule_editor.condition_field_help",
        "orchestrations.rule_editor.condition_operator",
        "orchestrations.rule_editor.condition_operator_help",
        "orchestrations.rule_editor.condition_value",
        "orchestrations.rule_editor.condition_value_help",
        "orchestrations.rule_editor.condition_group_mode",
        "orchestrations.rule_editor.condition_group_mode_help",
        "orchestrations.rule_editor.condition_all",
        "orchestrations.rule_editor.condition_any",
        "orchestrations.rule_editor.condition_none",
        "orchestrations.rule_editor.remove_condition",
        "orchestrations.rule_editor.remove_condition_group",
    }

    for locale in ("en", "ru", "de", "fr"):
        path = ROOT / "app" / "static" / "i18n" / locale / "orchestrations.json"
        catalog = json.loads(path.read_text(encoding="utf-8"))
        assert expected_keys <= set(catalog)
        assert all(catalog[key].strip() for key in expected_keys)

    assert "orchestrationConditionEditorHeader" in javascript
    assert "orchestrationConditionOperatorLabel" in javascript
    assert "orchestration-condition-editor-header" in javascript
    assert 'i18n.t("orchestrations.rule_editor.condition_field_help")' in javascript
    assert 'i18n.t("orchestrations.rule_editor.condition_operator_help")' in javascript
    assert 'i18n.t("orchestrations.rule_editor.condition_value_help")' in javascript
    assert '"orchestrations.rule_editor.operator_" + operator' in javascript


def test_orchestration_builder_supports_global_trace_level_action():
    javascript = (
        ROOT / "app" / "static" / "js" / "pages" / "orchestrations.js"
    ).read_text(encoding="utf-8")

    assert '"set_trace_level"' in javascript
    assert "orchestration-action-trace-level" in javascript
    assert 'orchestrationCurrent.scope !== "service"' in javascript
    for level in ("full", "compact", "disabled"):
        assert f'.val("{level}")' in javascript
