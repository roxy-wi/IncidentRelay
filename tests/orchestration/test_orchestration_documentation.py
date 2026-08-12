from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "usage" / "event-orchestration.md"


def test_event_orchestration_user_guide_covers_safe_user_workflow():
    content = GUIDE.read_text(encoding="utf-8")

    required_sections = (
        "# Event Orchestration user guide",
        "## A safe first rollout",
        "## Create your first orchestration",
        "## Conditions",
        "## Actions",
        "## Practical examples",
        "## Simulator",
        "## Shadow mode and executions",
        "## Webhook actions",
        "## Troubleshooting",
        "## Frequently asked questions",
    )
    for section in required_sections:
        assert section in content

    for safety_term in (
        "suppress",
        "pause",
        "drop",
        "shadow",
        "hybrid",
        "rollback",
        "Changed by",
        "Published by",
    ):
        assert safety_term in content


def test_event_orchestration_user_guide_is_linked_from_docs_navigation():
    navigation = (ROOT / "docs" / "mkdocs.yml").read_text(encoding="utf-8")
    usage_index = (ROOT / "docs" / "usage" / "index.md").read_text(encoding="utf-8")
    api_guide = (ROOT / "docs" / "api" / "event-orchestration.md").read_text(
        encoding="utf-8"
    )

    assert "Event Orchestration: usage/event-orchestration.md" in navigation
    assert "[Event Orchestration](event-orchestration.md)" in usage_index
    assert "[Event Orchestration user guide](../usage/event-orchestration.md)" in api_guide
