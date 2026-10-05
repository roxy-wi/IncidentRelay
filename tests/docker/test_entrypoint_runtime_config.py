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


def _render_runtime_config(tmp_path, source_body, extra_env=None):
    source = tmp_path / "incidentrelay.conf"
    source.write_text(source_body, encoding="utf-8")
    target = tmp_path / "runtime" / "incidentrelay.conf"

    subprocess.run(
        [sys.executable, "-", str(source), str(target)],
        input=_runtime_config_script(),
        text=True,
        env=_env(extra_env),
        check=True,
    )

    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser.read(target)
    return parser


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
