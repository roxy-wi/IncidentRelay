from pathlib import Path
import shutil
import subprocess
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "helm" / "incidentrelay"
SECRET_KEY = "config:\n  main:\n    secret_key: test-secret-key-for-helm-rendering\n"
METRICS_ENABLED = (
    "config:\n"
    "  main:\n"
    "    secret_key: test-secret-key-for-helm-rendering\n"
    "  metrics:\n"
    "    enabled: true\n"
)

requires_helm = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _helm_template(tmp_path, values_yaml, *args):
    values = tmp_path / "values.yaml"
    values.write_text(textwrap.dedent(values_yaml), encoding="utf-8")
    return subprocess.run(
        ["helm", "template", "incidentrelay", str(CHART), "-f", str(values), *args],
        text=True,
        capture_output=True,
    )


def _service_monitor_spec(manifest):
    return manifest[manifest.index("spec:"):].strip()


@requires_helm
def test_service_monitor_is_off_by_default(tmp_path):
    result = _helm_template(tmp_path, SECRET_KEY)

    assert result.returncode == 0, result.stderr
    assert "kind: ServiceMonitor" not in result.stdout


@requires_helm
def test_service_monitor_scrapes_the_web_service_with_the_token_secret(tmp_path):
    result = _helm_template(
        tmp_path,
        METRICS_ENABLED
        + """\
configFrom:
  metrics.auth_token:
    secretKeyRef:
      name: incidentrelay-metrics
      key: token
serviceMonitor:
  enabled: true
  interval: 30s
  scrapeTimeout: 10s
  labels:
    release: kube-prometheus-stack
  bearerTokenSecret:
    name: incidentrelay-metrics
    key: token
""",
        "--show-only",
        "templates/servicemonitor.yaml",
    )

    assert result.returncode == 0, result.stderr
    assert "kind: ServiceMonitor" in result.stdout
    assert "    release: kube-prometheus-stack\n" in result.stdout
    assert _service_monitor_spec(result.stdout) == textwrap.dedent(
        """\
        spec:
          selector:
            matchLabels:
              app.kubernetes.io/name: incidentrelay
              app.kubernetes.io/instance: incidentrelay
          endpoints:
            - port: http
              path: /metrics
              interval: "30s"
              scrapeTimeout: "10s"
              authorization:
                type: Bearer
                credentials:
                  name: "incidentrelay-metrics"
                  key: "token"
        """
    ).strip()


@requires_helm
def test_service_monitor_selects_the_web_service_port(tmp_path):
    result = _helm_template(tmp_path, SECRET_KEY, "--show-only", "templates/service.yaml")

    assert result.returncode == 0, result.stderr
    assert "    app.kubernetes.io/name: incidentrelay\n" in result.stdout
    assert "    app.kubernetes.io/instance: incidentrelay\n" in result.stdout
    assert "      name: http\n" in result.stdout


@requires_helm
def test_service_monitor_without_a_token_uses_no_authorization(tmp_path):
    result = _helm_template(
        tmp_path,
        METRICS_ENABLED + "serviceMonitor:\n  enabled: true\n",
        "--show-only",
        "templates/servicemonitor.yaml",
    )

    assert result.returncode == 0, result.stderr
    assert _service_monitor_spec(result.stdout) == textwrap.dedent(
        """\
        spec:
          selector:
            matchLabels:
              app.kubernetes.io/name: incidentrelay
              app.kubernetes.io/instance: incidentrelay
          endpoints:
            - port: http
              path: /metrics
        """
    ).strip()


@requires_helm
def test_service_monitor_with_an_existing_config_secret_trusts_its_metrics_section(tmp_path):
    result = _helm_template(
        tmp_path,
        "existingConfigSecret: incidentrelay-config\nserviceMonitor:\n  enabled: true\n",
    )

    assert result.returncode == 0, result.stderr
    assert "kind: ServiceMonitor" in result.stdout


@requires_helm
@pytest.mark.parametrize(
    ("values_yaml", "message"),
    [
        (
            SECRET_KEY + "serviceMonitor:\n  enabled: true\n",
            "serviceMonitor.enabled needs the /metrics endpoint",
        ),
        (
            METRICS_ENABLED + "    auth_token: plain-token\nserviceMonitor:\n  enabled: true\n",
            "/metrics requires metrics.auth_token",
        ),
        (
            METRICS_ENABLED
            + "configFrom:\n  metrics.auth_token:\n    secretKeyRef: {name: s, key: k}\n"
            + "serviceMonitor:\n  enabled: true\n",
            "/metrics requires metrics.auth_token",
        ),
        (
            "existingConfigSecret: incidentrelay-config\n"
            + "configFrom:\n  metrics.auth_token:\n    secretKeyRef: {name: s, key: k}\n"
            + "serviceMonitor:\n  enabled: true\n",
            "/metrics requires metrics.auth_token",
        ),
        (
            METRICS_ENABLED + "serviceMonitor:\n  enabled: true\n  bearerTokenSecret:\n    name: s\n",
            "serviceMonitor.bearerTokenSecret needs both name and key",
        ),
    ],
    ids=["metrics-disabled", "plain-token", "token-from-secret", "existing-config-secret", "token-without-key"],
)
def test_service_monitor_rejects_settings_it_cannot_scrape_with(tmp_path, values_yaml, message):
    result = _helm_template(tmp_path, values_yaml)

    assert result.returncode != 0
    assert message in result.stderr
