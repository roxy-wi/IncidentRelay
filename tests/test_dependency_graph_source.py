from pathlib import Path


SOURCE_PATH = Path("app/static/js/components/dependency_graph.js")


def test_dependency_graph_keeps_service_and_cytoscape_status_helpers_separate():
    source = SOURCE_PATH.read_text(encoding="utf-8")

    assert source.count("function serviceDependencyGraphServiceStatus(service)") == 1
    assert source.count("function serviceDependencyGraphNodeStatus(node)") == 1
    assert "function serviceDependencyGraphNodeStatus(service)" not in source


def test_dependency_graph_display_status_uses_service_status_helper():
    source = SOURCE_PATH.read_text(encoding="utf-8")
    start = source.index("function serviceDependencyGraphNodeDisplayStatus(service, impactMap)")
    end = source.index("function serviceDependencyGraphEdgeImpactStatus", start)
    function_source = source[start:end]

    assert "return serviceDependencyGraphServiceStatus(service);" in function_source
