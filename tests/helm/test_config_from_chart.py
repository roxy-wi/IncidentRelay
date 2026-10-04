from pathlib import Path
import shutil
import subprocess
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "helm" / "incidentrelay"
COMPONENTS = ("web", "scheduler", "slack", "telegram")

requires_helm = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _helm_template(tmp_path, values_yaml):
    values = tmp_path / "values.yaml"
    values.write_text(textwrap.dedent(values_yaml), encoding="utf-8")
    return subprocess.run(
        ["helm", "template", "incidentrelay", str(CHART), "-f", str(values)],
        text=True,
        capture_output=True,
    )


def _secret_env(name, secret, key):
    return (
        f"            - name: {name}\n"
        "              valueFrom:\n"
        "                secretKeyRef:\n"
        f"                  key: {key}\n"
        f"                  name: {secret}\n"
    )


def test_config_from_is_documented_and_wired_to_every_component():
    values = (CHART / "values.yaml").read_text(encoding="utf-8")
    assert "configFrom: {}" in values

    for component in COMPONENTS:
        deployment = (CHART / "templates" / f"deployment-{component}.yaml").read_text(encoding="utf-8")
        assert 'include "incidentrelay.configFromEnv"' in deployment


@requires_helm
def test_empty_config_from_renders_no_override_env(tmp_path):
    result = _helm_template(
        tmp_path,
        """\
        config:
          main:
            secret_key: test-secret-key-for-helm-rendering
        """,
    )

    assert result.returncode == 0, result.stderr
    assert "INCIDENTRELAY__" not in result.stdout


@requires_helm
def test_config_from_renders_secret_configmap_and_file_sources(tmp_path):
    result = _helm_template(
        tmp_path,
        """\
        config:
          main:
            secret_key: test-secret-key-for-helm-rendering
        configFrom:
          database.password:
            secretKeyRef:
              name: incidentrelay-db
              key: password
          server.public_base_url:
            configMapKeyRef:
              name: incidentrelay-settings
              key: public-base-url
          smtp.password:
            file: /mnt/secrets-store/smtp-password
        """,
    )

    assert result.returncode == 0, result.stderr
    rendered = result.stdout
    assert rendered.count(_secret_env("INCIDENTRELAY__DATABASE__PASSWORD", "incidentrelay-db", "password")) == 4
    assert rendered.count(
        "            - name: INCIDENTRELAY__SERVER__PUBLIC_BASE_URL\n"
        "              valueFrom:\n"
        "                configMapKeyRef:\n"
        "                  key: public-base-url\n"
        "                  name: incidentrelay-settings\n"
    ) == 4
    assert rendered.count(
        "            - name: INCIDENTRELAY__SMTP__PASSWORD__FILE\n"
        '              value: "/mnt/secrets-store/smtp-password"\n'
    ) == 4


@requires_helm
def test_secret_key_from_config_from_is_shared_by_empty_security_keys(tmp_path):
    result = _helm_template(
        tmp_path,
        """\
        config:
          auth:
            jwt_secret: separate-jwt-secret-for-helm-rendering
        configFrom:
          main.secret_key:
            secretKeyRef:
              name: incidentrelay-secrets
              key: secret-key
        """,
    )

    assert result.returncode == 0, result.stderr
    rendered = result.stdout
    for name in (
        "INCIDENTRELAY__MAIN__SECRET_KEY",
        "INCIDENTRELAY__MAIN__SECRET_ENCRYPTION_KEY",
        "INCIDENTRELAY__MATTERMOST__ACTION_SECRET",
        "INCIDENTRELAY__VOICE__CALLBACK_SECRET",
    ):
        assert rendered.count(_secret_env(name, "incidentrelay-secrets", "secret-key")) == 4, name
    # A key set explicitly in `config` keeps its own value.
    assert "INCIDENTRELAY__AUTH__JWT_SECRET" not in rendered
    assert "jwt_secret = separate-jwt-secret-for-helm-rendering" in rendered


@requires_helm
def test_existing_config_secret_does_not_get_shared_security_keys(tmp_path):
    result = _helm_template(
        tmp_path,
        """\
        existingConfigSecret: incidentrelay-config
        configFrom:
          main.secret_key:
            secretKeyRef:
              name: incidentrelay-secrets
              key: secret-key
        """,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("- name: INCIDENTRELAY__MAIN__SECRET_KEY\n") == 4
    assert "INCIDENTRELAY__AUTH__JWT_SECRET" not in result.stdout


@requires_helm
def test_secret_key_is_still_required_without_config_from(tmp_path):
    result = _helm_template(tmp_path, "config: {}\n")

    assert result.returncode != 0
    assert "config.main.secret_key is required" in result.stderr


@requires_helm
@pytest.mark.parametrize(
    ("config_from", "message"),
    [
        ("Database.Password:\n    file: /x", 'configFrom key "Database.Password" must look like <section>.<option>'),
        ("password:\n    file: /x", 'configFrom key "password" must look like <section>.<option>'),
        ("smtp.password: {}", "configFrom.smtp.password must set exactly one of"),
        (
            "smtp.password:\n    file: /x\n    secretKeyRef: {name: s, key: k}",
            "configFrom.smtp.password must set exactly one of",
        ),
        ("smtp.password:\n    path: /x", "configFrom.smtp.password must set exactly one of"),
    ],
)
def test_config_from_rejects_invalid_entries(tmp_path, config_from, message):
    result = _helm_template(
        tmp_path,
        "config:\n  main:\n    secret_key: test-secret-key-for-helm-rendering\n"
        f"configFrom:\n  {config_from}\n",
    )

    assert result.returncode != 0
    assert message in result.stderr
