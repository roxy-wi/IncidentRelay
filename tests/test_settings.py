import pytest

from app.settings import Settings, env_override_name


def write_config(path, body: str):
    path.write_text(body, encoding="utf-8")
    return path


def test_settings_read_basic_types(tmp_path):
    config_path = write_config(
        tmp_path / "incidentrelay.conf",
        """
[main]
name = IncidentRelay
enabled = true
count = 7
items = ["a", "b"]
""",
    )

    settings = Settings(str(config_path))

    assert settings.get("main", "name") == "IncidentRelay"
    assert settings.get_bool("main", "enabled") is True
    assert settings.get_int("main", "count") == 7
    assert settings.get_json("main", "items") == ["a", "b"]


def test_settings_returns_defaults_for_missing_values(tmp_path):
    config_path = write_config(
        tmp_path / "incidentrelay.conf",
        """
[main]
name = IncidentRelay
""",
    )

    settings = Settings(str(config_path))

    assert settings.get("missing", "value", "fallback") == "fallback"
    assert settings.get_int("missing", "value", 15) == 15
    assert settings.get_bool("missing", "value", True) is True
    assert settings.get_json("missing", "value", {"x": 1}) == {"x": 1}
    assert settings.get_section("missing", {"fallback": "yes"}) == {"fallback": "yes"}


def test_settings_invalid_json_raises_runtime_error(tmp_path):
    config_path = write_config(
        tmp_path / "incidentrelay.conf",
        """
[main]
bad_json = {invalid}
""",
    )

    settings = Settings(str(config_path))

    with pytest.raises(RuntimeError):
        settings.get_json("main", "bad_json")


def test_env_override_name_maps_section_and_option():
    assert env_override_name("database", "password") == "INCIDENTRELAY__DATABASE__PASSWORD"
    assert (
        env_override_name("browser_push", "vapid_private_key")
        == "INCIDENTRELAY__BROWSER_PUSH__VAPID_PRIVATE_KEY"
    )


def test_settings_without_env_overrides_read_the_config_file(tmp_path):
    config_path = write_config(
        tmp_path / "incidentrelay.conf",
        """
[database]
password = from-config
""",
    )

    settings = Settings(
        str(config_path),
        environ={"INCIDENTRELAY_CONFIG_FILE": "/other.conf", "INCIDENTRELAY__SMTP__PASSWORD": "x"},
    )

    assert settings.get("database", "password") == "from-config"


def test_env_override_takes_precedence_over_config_file(tmp_path):
    config_path = write_config(
        tmp_path / "incidentrelay.conf",
        """
[database]
password = from-config
port = 5432

[auth]
rbac_enforced = false
""",
    )

    settings = Settings(
        str(config_path),
        environ={
            "INCIDENTRELAY__DATABASE__PASSWORD": "from-env",
            "INCIDENTRELAY__DATABASE__PORT": "6432",
            "INCIDENTRELAY__AUTH__RBAC_ENFORCED": "true",
            "INCIDENTRELAY__MAIN__ITEMS": '["a", "b"]',
        },
    )

    assert settings.get("database", "password") == "from-env"
    assert settings.get_int("database", "port") == 6432
    assert settings.get_bool("auth", "rbac_enforced") is True
    assert settings.get_json("main", "items") == ["a", "b"]


def test_env_override_reads_value_from_file(tmp_path):
    config_path = write_config(
        tmp_path / "incidentrelay.conf",
        """
[smtp]
password = from-config
""",
    )
    secret_path = tmp_path / "smtp-password"
    secret_path.write_text("from-file\n", encoding="utf-8")

    settings = Settings(
        str(config_path),
        environ={"INCIDENTRELAY__SMTP__PASSWORD__FILE": str(secret_path)},
    )

    assert settings.get("smtp", "password") == "from-file"


def test_env_override_works_without_config_file(tmp_path):
    settings = Settings(
        str(tmp_path / "missing.conf"),
        environ={"INCIDENTRELAY__MAIN__SECRET_KEY": "from-env"},
    )

    assert settings.get("main", "secret_key") == "from-env"
    assert settings.get("main", "timezone", "UTC") == "UTC"


def test_env_override_rejects_value_and_file_together(tmp_path):
    settings = Settings(
        str(tmp_path / "missing.conf"),
        environ={
            "INCIDENTRELAY__DATABASE__PASSWORD": "from-env",
            "INCIDENTRELAY__DATABASE__PASSWORD__FILE": str(tmp_path / "password"),
        },
    )

    with pytest.raises(RuntimeError, match="use only one of them"):
        settings.get("database", "password")


def test_env_override_reports_unreadable_file(tmp_path):
    settings = Settings(
        str(tmp_path / "missing.conf"),
        environ={"INCIDENTRELAY__DATABASE__PASSWORD__FILE": str(tmp_path / "missing")},
    )

    with pytest.raises(RuntimeError, match="cannot read INCIDENTRELAY__DATABASE__PASSWORD__FILE"):
        settings.get("database", "password")


def test_get_section_overrides_options_from_the_file_and_keeps_their_spelling(tmp_path):
    config_path = write_config(
        tmp_path / "incidentrelay.conf",
        """
[voice_provider]
apiKey = from-config
token = from-config
region = eu
""",
    )
    token_path = tmp_path / "token"
    token_path.write_text("from-file\n", encoding="utf-8")

    settings = Settings(
        str(config_path),
        environ={
            "INCIDENTRELAY__VOICE_PROVIDER__APIKEY": "from-env",
            "INCIDENTRELAY__VOICE_PROVIDER__TOKEN__FILE": str(token_path),
        },
    )

    assert settings.get_section("voice_provider") == {
        "apiKey": "from-env",
        "token": "from-file",
        "region": "eu",
    }


def test_get_section_does_not_add_options_that_are_not_in_the_file(tmp_path):
    config_path = write_config(
        tmp_path / "incidentrelay.conf",
        """
[voice_provider]
region = eu
""",
    )

    settings = Settings(
        str(config_path),
        environ={
            "INCIDENTRELAY__VOICE_PROVIDER__APIKEY": "from-env",
            "INCIDENTRELAY__STUB_PROVIDER__TOKEN": "from-env",
        },
    )

    assert settings.get_section("voice_provider") == {"region": "eu"}
    assert settings.get_section("stub_provider", {"fallback": "yes"}) == {"fallback": "yes"}


def test_get_section_does_not_mix_sections_with_a_common_prefix(tmp_path):
    config_path = write_config(
        tmp_path / "incidentrelay.conf",
        """
[voice]
token = voice-from-config

[voice_provider]
token = provider-from-config
""",
    )

    settings = Settings(
        str(config_path),
        environ={"INCIDENTRELAY__VOICE_PROVIDER__TOKEN": "from-env"},
    )

    assert settings.get_section("voice") == {"token": "voice-from-config"}
    assert settings.get_section("voice_provider") == {"token": "from-env"}
