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


AUTHORIZATION = """\
      authorization:
        type: Bearer
        credentials:
          name: "{name}"
          key: "{key}"
"""


CONFIG_FROM_TOKEN = "configFrom:\n  metrics.auth_token:\n    secretKeyRef: {name: incidentrelay-metrics, key: token}\n"


def _web_extra_env_token(entry):
    return f"web:\n  extraEnv:\n    - name: INCIDENTRELAY__METRICS__AUTH_TOKEN{entry}\n"


EXTRA_ENV_TOKEN_SECRET = _web_extra_env_token(
    "\n      valueFrom:\n        secretKeyRef: {name: monitoring-secret, key: token}"
)


@requires_helm
@pytest.mark.parametrize(
    ("values_yaml", "name", "key"),
    [
        (
            METRICS_ENABLED + CONFIG_FROM_TOKEN + "serviceMonitor:\n  enabled: true\n",
            "incidentrelay-metrics",
            "token",
        ),
        (
            "existingConfigSecret: incidentrelay-config\n" + CONFIG_FROM_TOKEN + "serviceMonitor:\n  enabled: true\n",
            "incidentrelay-metrics",
            "token",
        ),
        (
            METRICS_ENABLED + EXTRA_ENV_TOKEN_SECRET + "serviceMonitor:\n  enabled: true\n",
            "monitoring-secret",
            "token",
        ),
        (
            "existingConfigSecret: incidentrelay-config\n"
            + "serviceMonitor:\n  enabled: true\n  bearerTokenSecret: {name: metrics-token, key: value}\n",
            "metrics-token",
            "value",
        ),
        (
            METRICS_ENABLED
            + _web_extra_env_token("\n      value: plain-token")
            + "serviceMonitor:\n  enabled: true\n  bearerTokenSecret: {name: metrics-token, key: value}\n",
            "metrics-token",
            "value",
        ),
    ],
    ids=[
        "from-config-from",
        "from-config-from-with-existing-config-secret",
        "from-web-extra-env",
        "explicit",
        "explicit-for-a-plain-value-in-web-extra-env",
    ],
)
def test_service_monitor_sends_the_token_secret(tmp_path, values_yaml, name, key):
    result = _helm_template(tmp_path, values_yaml, "--show-only", "templates/servicemonitor.yaml")

    assert result.returncode == 0, result.stderr
    assert AUTHORIZATION.format(name=name, key=key) in result.stdout


@requires_helm
def test_an_empty_token_in_web_extra_env_turns_token_authentication_off(tmp_path):
    # The variable wins over config.metrics.auth_token.
    result = _helm_template(
        tmp_path,
        METRICS_ENABLED
        + "    auth_token: plain-token\n"
        + _web_extra_env_token("\n      value: ''")
        + "serviceMonitor:\n  enabled: true\n",
        "--show-only",
        "templates/servicemonitor.yaml",
    )

    assert result.returncode == 0, result.stderr
    assert "authorization:" not in result.stdout


@requires_helm
@pytest.mark.parametrize(
    "values_yaml",
    [
        # An INCIDENTRELAY__METRICS__ENABLED variable wins over the config.
        "config:\n  main:\n    secret_key: test-secret-key-for-helm-rendering\n  metrics:\n    enabled: false\n"
        + "web:\n  extraEnv:\n    - name: INCIDENTRELAY__METRICS__ENABLED\n      value: 'true'\n"
        + "serviceMonitor:\n  enabled: true\n",
        # The chart can't see a value that comes from a Secret.
        SECRET_KEY
        + "configFrom:\n  metrics.enabled:\n    secretKeyRef: {name: s, key: k}\n"
        + "serviceMonitor:\n  enabled: true\n",
    ],
    ids=["enabled-in-extra-env", "enabled-from-a-secret"],
)
def test_service_monitor_accepts_metrics_enabled_outside_the_config(tmp_path, values_yaml):
    result = _helm_template(tmp_path, values_yaml)

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
            METRICS_ENABLED
            + "web:\n  extraEnv:\n    - name: INCIDENTRELAY__METRICS__ENABLED\n      value: 'false'\n"
            + "serviceMonitor:\n  enabled: true\n",
            "serviceMonitor.enabled needs the /metrics endpoint",
        ),
        (
            METRICS_ENABLED + "    auth_token: plain-token\nserviceMonitor:\n  enabled: true\n",
            "/metrics requires metrics.auth_token",
        ),
        (
            METRICS_ENABLED
            + "configFrom:\n  metrics.auth_token:\n    file: /mnt/secrets-store/metrics-token\n"
            + "serviceMonitor:\n  enabled: true\n",
            "/metrics requires metrics.auth_token",
        ),
        (
            METRICS_ENABLED
            + CONFIG_FROM_TOKEN
            + "serviceMonitor:\n  enabled: true\n  bearerTokenSecret: {name: other-secret, key: token}\n",
            "serviceMonitor.bearerTokenSecret differs from the Secret the web pod takes metrics.auth_token from "
            "(configFrom.metrics.auth_token)",
        ),
        (
            METRICS_ENABLED
            + EXTRA_ENV_TOKEN_SECRET
            + "serviceMonitor:\n  enabled: true\n  bearerTokenSecret: {name: other-secret, key: token}\n",
            "serviceMonitor.bearerTokenSecret differs from the Secret the web pod takes metrics.auth_token from "
            "(web.extraEnv)",
        ),
        (
            METRICS_ENABLED + _web_extra_env_token("\n      value: plain-token") + "serviceMonitor:\n  enabled: true\n",
            "the ServiceMonitor can't tell which Secret holds it (it comes from web.extraEnv)",
        ),
        (
            METRICS_ENABLED
            + _web_extra_env_token("\n      valueFrom:\n        configMapKeyRef: {name: c, key: token}")
            + "serviceMonitor:\n  enabled: true\n",
            "the ServiceMonitor can't tell which Secret holds it (it comes from web.extraEnv)",
        ),
        (
            METRICS_ENABLED + _web_extra_env_token("__FILE\n      value: /mnt/token") + "serviceMonitor:\n  enabled: true\n",
            "the ServiceMonitor can't tell which Secret holds it (it comes from web.extraEnv)",
        ),
        (
            METRICS_ENABLED + CONFIG_FROM_TOKEN + EXTRA_ENV_TOKEN_SECRET + "serviceMonitor:\n  enabled: true\n",
            "configFrom.metrics.auth_token and web.extraEnv (INCIDENTRELAY__METRICS__AUTH_TOKEN) set the same option",
        ),
        (
            METRICS_ENABLED + "serviceMonitor:\n  enabled: true\n  bearerTokenSecret:\n    name: s\n",
            "serviceMonitor.bearerTokenSecret needs both name and key",
        ),
    ],
    ids=[
        "metrics-disabled",
        "disabled-in-extra-env",
        "plain-token",
        "token-from-a-file",
        "different-token-secrets",
        "conflicts-with-web-extra-env",
        "plain-value-in-web-extra-env",
        "config-map-in-web-extra-env",
        "token-file-in-web-extra-env",
        "token-in-config-from-and-web-extra-env",
        "token-without-key",
    ],
)
def test_service_monitor_rejects_settings_it_cannot_scrape_with(tmp_path, values_yaml, message):
    result = _helm_template(tmp_path, values_yaml)

    assert result.returncode != 0
    assert message in result.stderr


@requires_helm
@pytest.mark.parametrize("component", ["web", "scheduler", "slack", "telegram"])
def test_every_component_keeps_its_metrics_files_in_its_own_directory(tmp_path, component):
    # prometheus_client keys its counter files by PID, so pods must not
    # share the directory on the data volume.
    result = _helm_template(tmp_path, SECRET_KEY, "--show-only", f"templates/deployment-{component}.yaml")

    assert result.returncode == 0, result.stderr
    assert "        - name: metrics\n          emptyDir: {}\n" in result.stdout
    assert "            - name: metrics\n              mountPath: /var/lib/incidentrelay/metrics\n" in result.stdout
