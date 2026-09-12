from pathlib import Path
import shutil
import subprocess
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "helm" / "incidentrelay"
TEMPLATES = CHART / "templates"


def _read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_custom_ca_values_and_helpers_are_registered():
    values = _read("helm/incidentrelay/values.yaml")
    helpers = _read("helm/incidentrelay/templates/_helpers.tpl")
    configmap = _read("helm/incidentrelay/templates/configmap-custom-ca.yaml")

    assert "customCA:" in values
    assert 'existingConfigMap: ""' in values
    assert "existingConfigMapKey: ca.crt" in values
    assert "systemBundlePath: /etc/ssl/certs/ca-certificates.crt" in values

    assert 'define "incidentrelay.customCAInitContainer"' in helpers
    assert 'cat "$SYSTEM_CA_BUNDLE" > /ca-work/ca-bundle.crt' in helpers
    assert "cat /custom-ca/ca.crt >> /ca-work/ca-bundle.crt" in helpers
    assert "REQUESTS_CA_BUNDLE" in helpers
    assert "SSL_CERT_FILE" in helpers
    assert 'fail "customCA.bundle and customCA.existingConfigMap are mutually exclusive' in helpers

    assert "kind: ConfigMap" in configmap
    assert "ca.crt: |-" in configmap


def test_custom_ca_is_wired_to_every_incidentrelay_component():
    for component in ("web", "scheduler", "slack", "telegram"):
        deployment = _read(
            f"helm/incidentrelay/templates/deployment-{component}.yaml"
        )
        assert 'include "incidentrelay.customCAChecksum"' in deployment
        assert 'include "incidentrelay.customCAInitContainer"' in deployment
        assert 'include "incidentrelay.customCAEnv"' in deployment
        assert 'include "incidentrelay.volumeMounts"' in deployment
        assert 'include "incidentrelay.volumes"' in deployment


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_custom_ca_inline_bundle_renders_combined_trust_for_all_components(tmp_path):
    values = tmp_path / "values.yaml"
    values.write_text(
        textwrap.dedent(
            """\
            config:
              main:
                secret_key: test-secret-key-for-helm-rendering
            customCA:
              bundle: |
                -----BEGIN CERTIFICATE-----
                TEST-CUSTOM-CA
                -----END CERTIFICATE-----
            """
        ),
        encoding="utf-8",
    )

    rendered = subprocess.check_output(
        ["helm", "template", "incidentrelay", str(CHART), "-f", str(values)],
        text=True,
    )

    assert "name: incidentrelay-custom-ca" in rendered
    assert "TEST-CUSTOM-CA" in rendered
    assert rendered.count("name: build-ca-bundle") == 4
    assert rendered.count("name: SSL_CERT_FILE") == 4
    assert rendered.count("name: REQUESTS_CA_BUNDLE") == 4
    assert 'cat "$SYSTEM_CA_BUNDLE" > /ca-work/ca-bundle.crt' in rendered
    assert "cat /custom-ca/ca.crt >> /ca-work/ca-bundle.crt" in rendered


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_custom_ca_existing_configmap_is_reused_without_rendering_another_configmap(tmp_path):
    values = tmp_path / "values.yaml"
    values.write_text(
        textwrap.dedent(
            """\
            config:
              main:
                secret_key: test-secret-key-for-helm-rendering
            customCA:
              existingConfigMap: company-ca
              existingConfigMapKey: company-root.pem
            """
        ),
        encoding="utf-8",
    )

    rendered = subprocess.check_output(
        ["helm", "template", "incidentrelay", str(CHART), "-f", str(values)],
        text=True,
    )

    assert "name: company-ca" in rendered
    assert "key: \"company-root.pem\"" in rendered
    assert "name: incidentrelay-custom-ca\n" not in rendered
    assert rendered.count("name: build-ca-bundle") == 4


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_custom_ca_rejects_inline_and_existing_configmap_together(tmp_path):
    values = tmp_path / "values.yaml"
    values.write_text(
        textwrap.dedent(
            """\
            config:
              main:
                secret_key: test-secret-key-for-helm-rendering
            customCA:
              bundle: test-ca
              existingConfigMap: company-ca
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["helm", "template", "incidentrelay", str(CHART), "-f", str(values)],
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "customCA.bundle and customCA.existingConfigMap are mutually exclusive" in (
        result.stdout + result.stderr
    )
