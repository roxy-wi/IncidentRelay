"""Release guards for the published OCI Helm chart."""

from __future__ import annotations

import re
from pathlib import Path


CHART = Path("helm") / "incidentrelay" / "Chart.yaml"
WORKFLOW = Path(".github") / "workflows" / "docker-image.yml"
OCI_CHART = "oci://ghcr.io/roxy-wi/incidentrelay-charts/incidentrelay"
OCI_REGISTRY = "ghcr.io/roxy-wi/incidentrelay-charts"


def _yaml_scalar(path: Path, key: str) -> str:
    prefix = f"{key}:"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith(prefix):
            continue
        value = line[len(prefix):].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value
    raise AssertionError(f"{key} is missing from {path}")


def test_chart_version_is_publishable_semver():
    chart_version = _yaml_scalar(CHART, "version")

    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", chart_version)


def test_helm_chart_is_published_only_after_the_docker_image():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "helm-publish:" in workflow
    assert "needs: build-and-push" in workflow
    assert "helm package" in workflow
    assert "helm push" in workflow
    assert f"CHART_REGISTRY: {OCI_REGISTRY.removeprefix('oci://')}" in workflow


def test_kubernetes_docs_use_the_published_oci_chart():
    for path in (
        Path("README.md"),
        Path("docs/getting-started/kubernetes.md"),
        Path("docs/ru/getting-started/kubernetes.md"),
    ):
        content = path.read_text(encoding="utf-8")
        assert OCI_CHART in content, path
