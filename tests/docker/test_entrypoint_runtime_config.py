import configparser
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / "docker" / "entrypoint.sh"
SHARED_SECRETS = (
    ("main", "secret_key"),
    ("main", "secret_encryption_key"),
    ("auth", "jwt_secret"),
    ("mattermost", "action_secret"),
    ("voice", "callback_secret"),
)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the entrypoint uses fcntl")


def _runtime_config_script():
    match = re.search(
        r"<<'PY_CONFIG'\n(.*?)\nPY_CONFIG\n",
        ENTRYPOINT.read_text(encoding="utf-8"),
        re.DOTALL,
    )
    assert match, "runtime config script not found in docker/entrypoint.sh"
    return match.group(1)


def _env(extra_env=None):
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("INCIDENTRELAY__")
    }
    env.update(extra_env or {})
    return env


def _start(tmp_path, source_body, extra_env=None):
    """
    Run the runtime config script like a container start and return the result.

    The runtime config in tmp_path/runtime persists between calls, like the
    copy on the data volume between container starts.
    """
    source = tmp_path / "incidentrelay.conf"
    source.write_text(source_body, encoding="utf-8")
    target = tmp_path / "runtime" / "incidentrelay.conf"

    return subprocess.run(
        [sys.executable, "-", str(source), str(target)],
        input=_runtime_config_script(),
        text=True,
        env=_env(extra_env),
        capture_output=True,
    )


def _runtime_config(tmp_path):
    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser.read(tmp_path / "runtime" / "incidentrelay.conf")
    return parser


def _render_runtime_config(tmp_path, source_body, extra_env=None):
    result = _start(tmp_path, source_body, extra_env)
    assert result.returncode == 0, result.stderr
    return _runtime_config(tmp_path)


def _effective_keys(config_path, extra_env):
    """Return the shared keys the application resolves from a runtime config."""
    script = (
        "import json\n"
        "from app.settings import Config\n"
        "print(json.dumps({\n"
        "    'secret_key': Config.SECRET_KEY,\n"
        "    'secret_encryption_key': Config.SECRET_ENCRYPTION_KEY,\n"
        "    'jwt_secret': Config.JWT_SECRET_KEY,\n"
        "    'action_secret': Config.MATTERMOST_ACTION_SECRET,\n"
        "    'callback_secret': Config.VOICE_CALLBACK_SECRET,\n"
        "}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", script],
        cwd=ROOT,
        env=_env({**extra_env, "INCIDENTRELAY_CONFIG_FILE": str(config_path)}),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_entrypoint_generates_missing_shared_secrets(tmp_path):
    parser = _render_runtime_config(tmp_path, "[main]\ntimezone = UTC\n")

    for section, option in SHARED_SECRETS:
        value = parser.get(section, option, fallback="")
        assert len(value) >= 32, f"{section}.{option} was not generated"


def test_entrypoint_keeps_configured_secrets(tmp_path):
    parser = _render_runtime_config(
        tmp_path,
        "[main]\nsecret_key = configured-secret-key-0123456789abcdef\n",
    )

    assert parser.get("main", "secret_key") == "configured-secret-key-0123456789abcdef"


def test_entrypoint_generates_shared_keys_when_secret_key_is_in_the_config(tmp_path):
    parser = _render_runtime_config(
        tmp_path,
        "[main]\nsecret_key = configured-secret-key-0123456789abcdef\n",
    )

    for section, option in SHARED_SECRETS[1:]:
        value = parser.get(section, option, fallback="")
        assert len(value) >= 32, f"{section}.{option} was not generated"


def test_entrypoint_does_not_generate_secrets_passed_through_env(tmp_path):
    parser = _render_runtime_config(
        tmp_path,
        "[main]\ntimezone = UTC\n",
        extra_env={
            "INCIDENTRELAY__MAIN__SECRET_KEY": "from-env",
            "INCIDENTRELAY__AUTH__JWT_SECRET__FILE": str(tmp_path / "jwt-secret"),
        },
    )

    for section, option in SHARED_SECRETS:
        assert parser.get(section, option, fallback="") == "", f"{section}.{option} was generated"


def test_entrypoint_clears_insecure_shared_keys_when_secret_key_comes_from_env(tmp_path):
    parser = _render_runtime_config(
        tmp_path,
        "[auth]\njwt_secret = change-this-jwt-secret\n",
        extra_env={"INCIDENTRELAY__MAIN__SECRET_KEY": "from-env"},
    )

    assert parser.get("auth", "jwt_secret") == ""


def test_secret_key_from_env_gives_every_pod_the_same_shared_keys(tmp_path):
    # existingConfigSecret + configFrom.main.secret_key: the mounted config has
    # no shared keys and each pod runs the entrypoint on its own emptyDir.
    secret_key = "secret-key-from-env-0123456789abcdef"
    extra_env = {"INCIDENTRELAY__MAIN__SECRET_KEY": secret_key}
    effective_keys = []

    for pod in ("pod-a", "pod-b"):
        pod_dir = tmp_path / pod
        pod_dir.mkdir()
        _render_runtime_config(pod_dir, "[main]\ntimezone = UTC\n", extra_env)
        effective_keys.append(
            _effective_keys(pod_dir / "runtime" / "incidentrelay.conf", extra_env)
        )

    assert effective_keys[0] == effective_keys[1]
    assert set(effective_keys[0].values()) == {secret_key}


def test_config_changes_apply_on_the_next_start(tmp_path):
    secret = "[main]\nsecret_key = configured-secret-key-0123456789abcdef\n"
    _render_runtime_config(tmp_path, secret + "[logging]\nlevel = INFO\n[database]\npassword = old\n")

    parser = _render_runtime_config(
        tmp_path, secret + "[logging]\nlevel = DEBUG\n[database]\npassword = new\n"
    )

    assert parser.get("logging", "level") == "DEBUG"
    assert parser.get("database", "password") == "new"


def test_generated_keys_are_kept_across_starts(tmp_path):
    first = _render_runtime_config(tmp_path, "[logging]\nlevel = INFO\n")
    second = _render_runtime_config(tmp_path, "[logging]\nlevel = DEBUG\n")

    for section, option in SHARED_SECRETS:
        assert second.get(section, option) == first.get(section, option), f"{section}.{option} changed"
    assert second.get("logging", "level") == "DEBUG"


def test_copy_from_the_previous_version_keeps_its_keys_but_not_its_settings(tmp_path):
    # Earlier versions read the copy instead of the mounted config, so a copy
    # on an existing volume can hold stale settings next to generated keys.
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "incidentrelay.conf").write_text(
        "[main]\n"
        "secret_key = stored-secret-key-0123456789abcdef\n"
        "secret_encryption_key = stored-encryption-key-0123456789abcdef\n"
        "[logging]\n"
        "level = INFO\n",
        encoding="utf-8",
    )

    parser = _render_runtime_config(tmp_path, "[logging]\nlevel = DEBUG\n")

    assert parser.get("logging", "level") == "DEBUG"
    assert parser.get("main", "secret_key") == "stored-secret-key-0123456789abcdef"
    assert parser.get("main", "secret_encryption_key") == "stored-encryption-key-0123456789abcdef"


def test_keys_stored_before_secret_key_moved_to_env_are_kept(tmp_path):
    first = _render_runtime_config(tmp_path, "[main]\ntimezone = UTC\n")

    parser = _render_runtime_config(
        tmp_path,
        "[main]\ntimezone = UTC\n",
        extra_env={"INCIDENTRELAY__MAIN__SECRET_KEY": "from-env"},
    )

    for section, option in SHARED_SECRETS[1:]:
        assert parser.get(section, option) == first.get(section, option), f"{section}.{option} changed"


def test_changed_encryption_key_refuses_to_start(tmp_path):
    base = "[main]\nsecret_key = configured-secret-key-0123456789abcdef\n"
    _render_runtime_config(tmp_path, base + "secret_encryption_key = old-encryption-key-0123456789abcdef\n")

    result = _start(tmp_path, base + "secret_encryption_key = new-encryption-key-0123456789abcdef\n")

    assert result.returncode != 0
    assert "main.secret_encryption_key differs" in result.stderr
    # The runtime config is left as it was, so restoring the old key works.
    parser = _runtime_config(tmp_path)
    assert parser.get("main", "secret_encryption_key") == "old-encryption-key-0123456789abcdef"


def _key_env(tmp_path, name, key, from_file):
    """Pass a key in an environment variable or through its __FILE form."""
    if not from_file:
        return {name: key}
    key_file = tmp_path / f"{name.lower()}.txt"
    key_file.write_text(key + "\n", encoding="utf-8")
    return {name + "__FILE": str(key_file)}


@pytest.mark.parametrize("from_file", [False, True], ids=["variable", "file"])
def test_changed_encryption_key_from_the_environment_refuses_to_start(tmp_path, from_file):
    base = "[main]\nsecret_key = configured-secret-key-0123456789abcdef\n"
    name = "INCIDENTRELAY__MAIN__SECRET_ENCRYPTION_KEY"

    _render_runtime_config(tmp_path, base, _key_env(tmp_path, name, "old-encryption-key-0123456789abcdef", from_file))
    assert _start(tmp_path, base, _key_env(tmp_path, name, "old-encryption-key-0123456789abcdef", from_file)).returncode == 0

    result = _start(tmp_path, base, _key_env(tmp_path, name, "new-encryption-key-0123456789abcdef", from_file))

    assert result.returncode != 0
    assert "main.secret_encryption_key differs" in result.stderr


@pytest.mark.parametrize("from_file", [False, True], ids=["variable", "file"])
def test_changed_secret_key_refuses_to_start_while_it_is_the_encryption_key(tmp_path, from_file):
    # With main.secret_key from the environment, an empty
    # main.secret_encryption_key falls back to it.
    base = "[main]\ntimezone = UTC\n"
    name = "INCIDENTRELAY__MAIN__SECRET_KEY"

    _render_runtime_config(tmp_path, base, _key_env(tmp_path, name, "old-secret-key-0123456789abcdef", from_file))
    assert _start(tmp_path, base, _key_env(tmp_path, name, "old-secret-key-0123456789abcdef", from_file)).returncode == 0

    result = _start(tmp_path, base, _key_env(tmp_path, name, "new-secret-key-0123456789abcdef", from_file))

    assert result.returncode != 0
    assert "main.secret_key, which is the encryption key" in result.stderr


def test_changed_secret_key_keeps_starting_with_a_separate_encryption_key(tmp_path):
    # Without main.secret_key in the environment, the entrypoint generates a
    # separate encryption key, so main.secret_key itself can change.
    _render_runtime_config(tmp_path, "[main]\nsecret_key = old-secret-key-0123456789abcdef\n")

    result = _start(tmp_path, "[main]\nsecret_key = new-secret-key-0123456789abcdef\n")

    assert result.returncode == 0, result.stderr


def test_unreadable_key_file_refuses_to_start(tmp_path):
    result = _start(
        tmp_path,
        "[main]\ntimezone = UTC\n",
        {"INCIDENTRELAY__MAIN__SECRET_KEY__FILE": str(tmp_path / "missing")},
    )

    assert result.returncode != 0
    assert "cannot read INCIDENTRELAY__MAIN__SECRET_KEY__FILE" in result.stderr


def test_encryption_key_from_the_environment_is_not_written(tmp_path):
    _render_runtime_config(
        tmp_path,
        "[main]\nsecret_key = configured-secret-key-0123456789abcdef\n",
        {"INCIDENTRELAY__MAIN__SECRET_ENCRYPTION_KEY": "env-encryption-key-0123456789abcdef"},
    )

    runtime_config = (tmp_path / "runtime" / "incidentrelay.conf").read_text(encoding="utf-8")
    assert "env-encryption-key-0123456789abcdef" not in runtime_config


def test_encryption_key_moved_to_the_environment_keeps_starting(tmp_path):
    base = "[main]\nsecret_key = configured-secret-key-0123456789abcdef\n"
    _render_runtime_config(tmp_path, base + "secret_encryption_key = encryption-key-0123456789abcdef0123\n")

    result = _start(
        tmp_path,
        base,
        {"INCIDENTRELAY__MAIN__SECRET_ENCRYPTION_KEY": "encryption-key-0123456789abcdef0123"},
    )

    assert result.returncode == 0, result.stderr


def test_changed_encryption_key_refuses_to_start_after_upgrading(tmp_path):
    # Copies written by earlier versions hold the key itself, but no key check.
    base = "[main]\nsecret_key = configured-secret-key-0123456789abcdef\n"
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "incidentrelay.conf").write_text(
        base + "secret_encryption_key = old-encryption-key-0123456789abcdef\n",
        encoding="utf-8",
    )

    result = _start(tmp_path, base + "secret_encryption_key = new-encryption-key-0123456789abcdef\n")

    assert result.returncode != 0
    assert "main.secret_encryption_key differs" in result.stderr
