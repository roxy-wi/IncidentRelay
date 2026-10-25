"""Restricted-style Helm defaults for every service and the custom CA init."""

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "helm" / "incidentrelay"
COMPONENTS = ("web", "scheduler", "telegram", "slack")


def test_secure_defaults_apply_to_all_components_and_custom_ca_init():
    values = (CHART / "values.yaml").read_text(encoding="utf-8")
    pod = values.split("\npodSecurityContext:\n", 1)[1].split(
        "\nsecurityContext:\n", 1
    )[0]
    container = values.split("\nsecurityContext:\n", 1)[1].split(
        "\nextraVolumes:", 1
    )[0]
    for setting in (
        "runAsNonRoot: true",
        "runAsUser: 10001",
        "runAsGroup: 10001",
        "fsGroup: 10001",
        "fsGroupChangePolicy: OnRootMismatch",
    ):
        assert setting in pod
    for setting in (
        "allowPrivilegeEscalation: false",
        "drop:",
        "- ALL",
        "seccompProfile:",
        "type: RuntimeDefault",
    ):
        assert setting in container
    for component in COMPONENTS:
        template = (CHART / "templates" / f"deployment-{component}.yaml").read_text()
        assert "{{- with .Values.podSecurityContext }}" in template
        assert "{{- with .Values.securityContext }}" in template
        assert 'include "incidentrelay.customCAInitContainer"' in template

    helpers = (CHART / "templates" / "_helpers.tpl").read_text()
    init = helpers.split('define "incidentrelay.customCAInitContainer"', 1)[1]
    init = init.split('define "incidentrelay.volumes"', 1)[0]
    assert "{{- with .Values.securityContext }}" in init


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
@pytest.mark.parametrize("with_custom_ca", [False, True])
def test_rendered_helm_pods_and_init_obey_non_root_defaults(with_custom_ca):
    overrides = ["--set-string", "config.main.secret_key=helm-test-secret-key"]
    if with_custom_ca:
        overrides.extend(["--set-string", "customCA.bundle=TEST-CERTIFICATE"])
    rendered = subprocess.check_output(
        ["helm", "template", "incidentrelay", str(CHART), *overrides], text=True
    )
    deployments = [
        document for document in rendered.split("---")
        if "kind: Deployment\n" in document
    ]
    assert len(deployments) == 4
    for deployment in deployments:
        assert "runAsNonRoot: true" in deployment
        assert "runAsUser: 10001" in deployment
        assert "runAsGroup: 10001" in deployment
        assert "fsGroup: 10001" in deployment
        assert "fsGroupChangePolicy: OnRootMismatch" in deployment
        expected_containers = 2 if with_custom_ca else 1
        assert deployment.count("allowPrivilegeEscalation: false") == expected_containers
        assert deployment.count("type: RuntimeDefault") == expected_containers
        assert deployment.count("- ALL") == expected_containers
        assert ("name: build-ca-bundle" in deployment) == with_custom_ca
