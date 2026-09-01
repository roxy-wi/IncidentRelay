from pathlib import Path
from types import SimpleNamespace

import pytest

from app.settings import validate_security_configuration


ROOT = Path(__file__).resolve().parents[2]


def test_security_config_rejects_known_default_jwt_secret():
    config = SimpleNamespace(
        SECRET_KEY="unique-main-secret",
        JWT_SECRET_KEY="dev-secret-key",
    )
    with pytest.raises(RuntimeError, match="auth.jwt_secret"):
        validate_security_configuration(config)


def test_security_config_rejects_missing_main_secret():
    config = SimpleNamespace(
        SECRET_KEY="",
        JWT_SECRET_KEY="unique-jwt-secret",
    )
    with pytest.raises(RuntimeError, match="main.secret_key"):
        validate_security_configuration(config)


def test_stock_deployment_does_not_ship_known_authentication_secret():
    docker_config = (ROOT / "docker" / "incidentrelay.docker.conf").read_text()
    helm_values = (ROOT / "helm" / "incidentrelay" / "values.yaml").read_text()
    rpm_config = (ROOT / "etc" / "incidentrelay" / "incidentrelay.conf").read_text()
    for value in ("dev-secret-key", "change-this-jwt-secret"):
        assert value not in docker_config
        assert value not in helm_values
        assert value not in rpm_config


def test_webhook_urls_are_treated_as_credentials_in_audit_redaction():
    from app.modules.redaction import REDACTED, redact_secrets

    result = redact_secrets({
        "config": {
            "webhook_url": "https://hooks.example/services/secret/path",
            "api_url": "https://mattermost.example",
        }
    })

    assert result["config"]["webhook_url"] == REDACTED
    assert result["config"]["api_url"] == "https://mattermost.example"
