import configparser
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


def _render_runtime_config(tmp_path, source_body, extra_env=None):
    source = tmp_path / "incidentrelay.conf"
    source.write_text(source_body, encoding="utf-8")
    target = tmp_path / "runtime" / "incidentrelay.conf"
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("INCIDENTRELAY__")
    }
    env.update(extra_env or {})

    subprocess.run(
        [sys.executable, "-", str(source), str(target)],
        input=_runtime_config_script(),
        text=True,
        env=env,
        check=True,
    )

    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser.read(target)
    return parser


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


def test_entrypoint_does_not_generate_secrets_passed_through_env(tmp_path):
    parser = _render_runtime_config(
        tmp_path,
        "[main]\ntimezone = UTC\n",
        extra_env={
            "INCIDENTRELAY__MAIN__SECRET_KEY": "from-env",
            "INCIDENTRELAY__AUTH__JWT_SECRET__FILE": str(tmp_path / "jwt-secret"),
        },
    )

    assert parser.get("main", "secret_key", fallback="") == ""
    assert parser.get("auth", "jwt_secret", fallback="") == ""
    assert len(parser.get("mattermost", "action_secret", fallback="")) >= 32
