"""Non-root container entrypoint and symlink-safe volume upgrade checks."""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def ownership_module():
    path = ROOT / "docker" / "fix_volume_permissions.py"
    spec = importlib.util.spec_from_file_location("fix_volume_permissions", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(sys.platform != "linux", reason="container ownership relies on Linux APIs")
def test_existing_correct_ownership_is_not_changed(tmp_path, monkeypatch, ownership_module):
    volume = tmp_path / "volume"
    (volume / "metrics").mkdir(parents=True)
    (volume / "incidentrelay.db").write_text("database")

    def unexpected(*args, **kwargs):
        raise AssertionError("chown should be skipped for correctly owned files")

    monkeypatch.setattr(os, "fchown", unexpected)
    monkeypatch.setattr(os, "chown", unexpected)
    assert ownership_module.fix_volume_ownership(
        str(volume), uid=os.getuid(), gid=os.getgid()
    ) == 0


@pytest.mark.skipif(sys.platform != "linux", reason="container ownership relies on Linux APIs")
def test_existing_root_owned_volume_and_config_are_repaired_once(
    tmp_path, monkeypatch, ownership_module
):
    volume = tmp_path / "data"
    volume.mkdir()
    nested = volume / "metrics"
    nested.mkdir()
    (volume / "incidentrelay.conf").write_text("[main]\nsecret_key = test\n")
    (volume / "incidentrelay.conf.lock").write_text("")
    (volume / "incidentrelay.db").write_text("")
    (nested / "counter.db").write_text("")

    fixed_dir_fds = []
    fixed_file_names = []
    monkeypatch.setattr(os, "fchown", lambda fd, uid, gid: fixed_dir_fds.append(fd))
    monkeypatch.setattr(
        os, "chown",
        lambda name, uid, gid, **kwargs: fixed_file_names.append(
            (name, kwargs.get("follow_symlinks"))
        ),
    )

    new_uid, new_gid = os.getuid() + 10001, os.getgid() + 10001
    count = ownership_module.fix_volume_ownership(
        str(volume), uid=new_uid, gid=new_gid
    )
    assert count == 6  # two directories, four regular files
    assert len(fixed_dir_fds) == 2
    assert set(fixed_file_names) == {
        ("incidentrelay.conf", False),
        ("incidentrelay.conf.lock", False),
        ("incidentrelay.db", False),
        ("counter.db", False),
    }


@pytest.mark.skipif(sys.platform != "linux", reason="container ownership relies on Linux APIs")
def test_volume_symlinks_never_change_files_outside_the_volume(
    tmp_path, monkeypatch, ownership_module
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("do not touch")

    volume = tmp_path / "volume"
    volume.mkdir()
    (volume / "nested").mkdir()
    (volume / "nested" / "actual").write_text("data")
    (volume / "outside-file").symlink_to(outside / "secret")
    (volume / "outside-directory").symlink_to(outside, target_is_directory=True)
    (volume / "nested" / "relative-link").symlink_to("../../outside/secret")

    files = []
    dirs = []
    monkeypatch.setattr(os, "fchown", lambda fd, uid, gid: dirs.append(fd))
    monkeypatch.setattr(
        os, "chown", lambda name, uid, gid, **kwargs: files.append(name)
    )

    count = ownership_module.fix_volume_ownership(
        str(volume), uid=os.getuid() + 10001, gid=os.getgid() + 10001
    )
    assert count == 3  # root, nested directory, actual file
    assert files == ["actual"]
    assert len(dirs) == 2
    assert (outside / "secret").read_text() == "do not touch"


@pytest.mark.skipif(sys.platform != "linux", reason="container ownership relies on Linux APIs")
def test_symlink_as_a_volume_root_is_rejected(tmp_path, ownership_module):
    actual = tmp_path / "actual"
    actual.mkdir()
    root = tmp_path / "linked"
    root.symlink_to(actual, target_is_directory=True)
    with pytest.raises(OSError):
        ownership_module.fix_volume_ownership(
            str(root), uid=os.getuid(), gid=os.getgid()
        )


def test_dockerfile_explicitly_installs_privilege_drop_and_creates_home():
    dockerfile = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    assert "util-linux" in dockerfile  # explicit setpriv dependency
    assert "passwd" in dockerfile
    assert "groupadd --gid 10001 incidentrelay" in dockerfile
    assert "useradd --uid 10001 --gid 10001 --create-home" in dockerfile
    assert "ENV HOME=/home/incidentrelay" in dockerfile
    assert "COPY . /opt/incidentrelay" in dockerfile
    # Root is only the bootstrap identity. No service continues as root.
    assert not any(line.startswith("USER ") for line in dockerfile.splitlines())


def test_entrypoint_drops_privileges_before_migrations_and_all_services():
    entrypoint_path = ROOT / "docker" / "entrypoint.sh"
    assert b"\r\n" not in entrypoint_path.read_bytes(), (
        "docker/entrypoint.sh has CRLF line endings; Bash scripts must use LF"
    )
    entrypoint = entrypoint_path.read_text(encoding="utf-8")
    assert entrypoint.index("PY_CONFIG\n") < entrypoint.index(
        "python /opt/incidentrelay/docker/fix_volume_permissions.py"
    )
    assert entrypoint.index("fix_volume_permissions.py") < entrypoint.index(
        "exec setpriv --reuid=10001 --regid=10001 --clear-groups -- /entrypoint.sh"
    )
    assert entrypoint.index("exec setpriv --reuid=10001") < entrypoint.index(
        'if [ "${INCIDENTRELAY_RUN_MIGRATIONS:-0}" = "1" ]'
    )
    assert "if [ \"$(id -u)\" -eq 0 ]; then" in entrypoint
    assert "export HOME=/tmp" in entrypoint
    assert "exec /bin/bash" in entrypoint
    syntax = subprocess.run(["bash", "-n", str(ROOT / "docker" / "entrypoint.sh")])
    assert syntax.returncode == 0


@pytest.mark.skipif(
    sys.platform != "linux" or os.geteuid() != 0 or shutil.which("setpriv") is None,
    reason="requires root and setpriv for a safe end-to-end bootstrap simulation",
)
def test_root_bootstrap_preserves_secrets_and_runs_shell_as_unprivileged_user():
    """Run the actual entrypoint safely against disposable substituted paths."""
    import configparser
    import tempfile

    with tempfile.TemporaryDirectory(prefix="incidentrelay-nonroot-") as dirname:
        base = Path(dirname)
        base.chmod(0o755)  # required for the subprocess after dropping root
        config_dir = base / "etc"
        config_dir.mkdir()
        source = config_dir / "incidentrelay.conf"
        source.write_text("[main]\ntimezone = UTC\n", encoding="utf-8")
        data, logs = base / "data", base / "logs"
        data.mkdir()
        logs.mkdir()
        (data / "incidentrelay.db").write_text("existing database placeholder")
        outsider = base / "outside"
        outsider.write_text("root only")
        outsider.chmod(0o600)
        (data / "outside-symlink").symlink_to(outsider)
        home = base / "home"
        home.mkdir()
        os.chown(home, 10001, 10001)

        script = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
        for old, new in (
            ("/etc/incidentrelay/incidentrelay.conf", str(source)),
            ("/var/lib/incidentrelay", str(data)),
            ("/var/log/incidentrelay", str(logs)),
            ("/home/incidentrelay", str(home)),
            ("/opt/incidentrelay/docker/fix_volume_permissions.py", str(base / "repair.py")),
            ("/entrypoint.sh", str(base / "entrypoint.sh")),
        ):
            script = script.replace(old, new)
        entrypoint = base / "entrypoint.sh"
        entrypoint.write_text(script, encoding="utf-8")
        entrypoint.chmod(0o755)

        repair = (ROOT / "docker" / "fix_volume_permissions.py").read_text()
        repair = repair.replace(
            'VOLUME_DIRS = ("/var/lib/incidentrelay", "/var/log/incidentrelay")',
            f"VOLUME_DIRS = ({str(data)!r}, {str(logs)!r})",
        )
        (base / "repair.py").write_text(repair, encoding="utf-8")

        env = os.environ.copy()
        env["INCIDENTRELAY_CONFIG_FILE"] = str(source)
        env["INCIDENTRELAY_SERVICE"] = "shell"
        env["INCIDENTRELAY_RUN_MIGRATIONS"] = "0"
        env["HOME"] = str(home)
        initial_key = None
        for _ in range(2):
            result = subprocess.run(
                ["bash", str(entrypoint)],
                input="id -u; id -g; printf 'HOME=%s\\n' \"$HOME\"; exit\n",
                text=True,
                capture_output=True,
                env=env,
                timeout=25,
            )
            assert result.returncode == 0, result.stderr
            assert "10001\n10001\n" in result.stdout
            assert f"HOME={home}" in result.stdout
            runtime = data / "incidentrelay.conf"
            parser = configparser.ConfigParser()
            parser.read(runtime)
            key = parser.get("main", "secret_key")
            assert len(key) >= 32
            if initial_key is not None:
                assert key == initial_key
            initial_key = key
            assert runtime.stat().st_uid == 10001
            assert runtime.stat().st_mode & 0o777 == 0o600
            assert (data / "metrics" / "shell").stat().st_uid == 10001
            assert outsider.stat().st_uid == 0
            assert (data / "outside-symlink").is_symlink()


@pytest.mark.skipif(
    sys.platform != "linux" or os.geteuid() != 0 or shutil.which("setpriv") is None,
    reason="requires root and setpriv to simulate an arbitrary container UID",
)
def test_arbitrary_non_root_uid_does_not_attempt_chown_and_gets_writable_home():
    import tempfile

    with tempfile.TemporaryDirectory(prefix="incidentrelay-arbitrary-uid-") as dirname:
        base = Path(dirname)
        base.chmod(0o755)
        home = base / "home"
        home.mkdir()
        home.chmod(0o755)
        data = base / "data"
        data.mkdir()
        os.chown(data, 12345, 12345)
        config = base / "external.conf"
        config.write_text("[main]\nsecret_key = test-external-secret-key\n")
        config.chmod(0o644)

        script = (ROOT / "docker" / "entrypoint.sh").read_text()
        script = script.replace("/var/lib/incidentrelay", str(data))
        script = script.replace("/home/incidentrelay", str(home))
        entrypoint = base / "entrypoint.sh"
        entrypoint.write_text(script)
        entrypoint.chmod(0o755)

        env = os.environ.copy()
        env.update({
            "INCIDENTRELAY_CONFIG_FILE": str(config),
            "INCIDENTRELAY_SERVICE": "shell",
            "INCIDENTRELAY_RUN_MIGRATIONS": "0",
            "HOME": str(home),
        })
        result = subprocess.run(
            [
                "setpriv", "--reuid=12345", "--regid=12345", "--clear-groups",
                "--", "bash", str(entrypoint),
            ],
            input="id -u; printf 'HOME=%s\\n' \"$HOME\"; exit\n",
            text=True,
            capture_output=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert "12345\n" in result.stdout
        assert "HOME=/tmp" in result.stdout
        assert (data / "metrics" / "shell").stat().st_uid == 12345
