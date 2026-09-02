import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "app" / "templates" / "pages" / "orchestrations.html"
SCRIPT = ROOT / "app" / "static" / "js" / "pages" / "orchestrations.js"
STYLE = ROOT / "app" / "static" / "css" / "orchestrations.css"


def test_simulator_uses_human_readable_result_views():
    template = TEMPLATE.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    style = STYLE.read_text(encoding="utf-8")

    for tab in ("summary", "rules", "changes", "raw"):
        assert f'data-simulation-result-tab="{tab}"' in template
        assert f'data-simulation-result-panel="{tab}"' in template

    assert 'id="orchestration-simulation-overview"' in template
    assert 'id="orchestration-simulation-summary"' in template
    assert 'id="orchestration-simulation-rules"' in template
    assert 'id="orchestration-simulation-changes"' in template
    assert 'id="orchestration-simulation-result"' in template

    for function_name in (
        "renderOrchestrationSimulationOverview",
        "renderOrchestrationSimulationSummary",
        "renderOrchestrationSimulationRules",
        "renderOrchestrationSimulationChanges",
        "renderOrchestrationSimulationResult",
    ):
        assert f"function {function_name}" in script

    assert "result.input_output_diff" in script
    assert "result.active_draft_diff" in script
    assert ".orchestration-simulation-kv-grid" in style
    assert ".orchestration-simulation-rule" in style
    assert ".orchestration-simulation-diff-table" in style


def test_simulator_result_keys_exist_in_every_locale():
    required = {
        "orchestrations.simulator.summary",
        "orchestrations.simulator.rules",
        "orchestrations.simulator.changes",
        "orchestrations.simulator.raw_json",
        "orchestrations.simulator.input_output_changes",
        "orchestrations.simulator.active_draft_changes",
        "orchestrations.simulator.matched_rules",
        "orchestrations.simulator.actual",
    }

    for locale in ("en", "ru", "de", "fr", "zh"):
        catalog = json.loads(
            (ROOT / "app" / "static" / "i18n" / locale / "orchestrations.json").read_text(
                encoding="utf-8"
            )
        )
        assert required <= set(catalog)
