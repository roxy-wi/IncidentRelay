import base64
import fcntl
import os
import subprocess
import sys
import textwrap
import types
from contextlib import contextmanager

from prometheus_client.mmap_dict import MmapedDict

from tests.metrics.exposition import parse_exposition, sample_value

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Children cannot set Config.METRICS_ENABLED in the snippet: importing
# anything from the app package already imports the metrics module and
# runs its init. They get a config file instead, like a real deployment.
_TEST_CONFIG = os.path.join(ROOT_DIR, "tests", "incidentrelay.test.conf")

_RECORD_ALERTS = """
    from app.services.metrics import record_alert_received
    for _ in range({count}):
        record_alert_received({source!r})
    print("READY", flush=True)
    sys.stdin.read()
"""

_RECORD_ALERTS_AND_EXIT = """
    from app.services.metrics import record_alert_received
    record_alert_received({source!r})
"""

_RECORD_ACTION = """
    from app.services.metrics import record_alert_group_action
    record_alert_group_action({action!r})
    print("READY", flush=True)
    sys.stdin.read()
"""

_RENDER = """
    import base64
    from app.services.metrics import render_exposition
    sys.stdout.buffer.write(base64.b64encode(render_exposition()))
"""

_BREAK_DATABASE = """
    import app.services.metrics as business_metrics
    import app.services.readiness as readiness

    def _broken():
        raise RuntimeError("connection refused")

    business_metrics.init_database = _broken
    readiness.init_database = _broken
"""


def _write_child_config(directory, enabled=True):
    """Write a child config: the test config plus a [metrics] section."""

    config = os.path.join(directory, "incidentrelay-child.conf")
    content = open(_TEST_CONFIG).read()
    content += f"\n[metrics]\nenabled = {'true' if enabled else 'false'}\n"
    with open(config, "w") as handle:
        handle.write(content)

    return config


def _snippet(body):
    """Wrap a snippet with the imports every child needs."""

    return (
        "import sys\n"
        f"sys.path.insert(0, {ROOT_DIR!r})\n"
        f"{textwrap.dedent(body).strip()}\n"
    )


def _child_environment(multiproc_dir, config_file):
    environment = os.environ.copy()
    environment["PROMETHEUS_MULTIPROC_DIR"] = str(multiproc_dir)
    environment["INCIDENTRELAY_CONFIG_FILE"] = str(config_file)
    # The legacy typo name must not shadow the child config.
    environment.pop("INCEDENTRELAY_CONFIG_FILE", None)
    environment["PYTHONPATH"] = os.pathsep.join(
        [ROOT_DIR, environment.get("PYTHONPATH", "")],
    )

    return environment


def _run_child(code, multiproc_dir, config_file):
    """Run one child process with the multiprocess directory configured."""

    return subprocess.run(
        [sys.executable, "-c", code],
        env=_child_environment(multiproc_dir, config_file),
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )


@contextmanager
def _live_recorder(code, multiproc_dir, config_file):
    """
    Run a recorder child that stays alive until the block ends.

    The child records, signals READY and then blocks; closing our end of
    its stdin stops it. If it dies before READY (import error, crash),
    the assertion surfaces its stderr instead of a confusing KeyError.
    """

    process = subprocess.Popen(
        [sys.executable, "-c", code],
        env=_child_environment(multiproc_dir, config_file),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        ready = process.stdout.readline().strip()
        assert ready == "READY", process.stderr.read()

        yield process
    finally:
        if process.stdin:
            process.stdin.close()

        process.wait(timeout=30)


def _record_alerts(multiproc_dir, count=1, source="grafana"):
    return _live_recorder(
        _snippet(_RECORD_ALERTS.format(count=count, source=source)),
        multiproc_dir,
        _write_child_config(multiproc_dir),
    )


def _record_action(multiproc_dir, action="resolved"):
    return _live_recorder(
        _snippet(_RECORD_ACTION.format(action=action)),
        multiproc_dir,
        _write_child_config(multiproc_dir),
    )


def _render(multiproc_dir, setup=""):
    """Render the exposition in a fresh child process; return the body."""

    result = _run_child(
        _snippet(setup + _RENDER),
        multiproc_dir,
        _write_child_config(multiproc_dir),
    )

    return base64.b64decode(result.stdout)


def _assert_no_pid_labels(families):
    """Merged exposition must never leak per-process series."""

    for family in families.values():
        for sample in family.samples:
            assert "pid" not in sample.labels, (family.name, sample.labels)


def test_counters_from_other_processes_are_aggregated(tmp_path):
    """Events recorded by two separate processes must sum in one scrape."""

    with _record_alerts(tmp_path, count=3), _record_alerts(
        tmp_path,
        count=2,
        source="pagertree",
    ):
        families = parse_exposition(_render(tmp_path))

    assert (
        sample_value(
            families,
            "incidentrelay_alerts_received_total",
            {"source": "grafana"},
        )
        == 3.0
    )
    assert (
        sample_value(
            families,
            "incidentrelay_alerts_received_total",
            {"source": "pagertree"},
        )
        == 2.0
    )
    _assert_no_pid_labels(families)


def test_worker_daemon_actions_are_visible_in_web_scrape(tmp_path):
    """
    The maintainer's blocker: lifecycle transitions performed by the
    scheduler/Telegram/Slack daemons must show up in the web /metrics.
    A daemon subprocess records an action; a web-like child renders it.
    """

    with _record_action(tmp_path, action="resolved"):
        families = parse_exposition(_render(tmp_path))

    assert (
        sample_value(
            families,
            "incidentrelay_alert_group_actions_total",
            {"action": "resolved"},
        )
        == 1.0
    )


def test_scrape_reflects_events_recorded_between_scrapes(tmp_path):
    """Two scrapes must behave like Prometheus scraping twice: grow."""

    with _record_alerts(tmp_path, count=2) as first_recorder:
        first = parse_exposition(_render(tmp_path))

        with _record_alerts(tmp_path, count=2):
            second = parse_exposition(_render(tmp_path))

    del first_recorder

    first_value = sample_value(
        first,
        "incidentrelay_alerts_received_total",
        {"source": "grafana"},
    )
    second_value = sample_value(
        second,
        "incidentrelay_alerts_received_total",
        {"source": "grafana"},
    )

    assert first_value == 2.0
    assert second_value == first_value + 2.0


def test_database_gauges_render_exactly_once(tmp_path):
    """
    The database gauges are computed by the scrape itself, so however
    many processes recorded counters, each gauge must appear once —
    never one copy per contributing process.
    """

    with _record_alerts(tmp_path, count=1), _record_alerts(tmp_path, count=1):
        families = parse_exposition(_render(tmp_path))

    assert len(families["incidentrelay_database_up"].samples) == 1
    assert len(families["incidentrelay_build_info"].samples) == 1
    assert len(families["incidentrelay_scheduler_last_run_timestamp_seconds"].samples) == 1
    assert sample_value(families, "incidentrelay_database_up", {}) == 1.0
    _assert_no_pid_labels(families)


def test_database_outage_degrades_gauges_in_multiprocess_mode(tmp_path):
    """
    Same outage contract as single-process mode: database_up 0, absent
    delivery gauges, heartbeat 0, and the exposition still renders.
    """

    with _record_alerts(tmp_path, count=1):
        families = parse_exposition(_render(tmp_path, setup=_BREAK_DATABASE))

    assert sample_value(families, "incidentrelay_database_up", {}) == 0.0
    assert (
        sample_value(
            families,
            "incidentrelay_scheduler_last_run_timestamp_seconds",
            {},
        )
        == 0.0
    )
    # During the outage the recent delivery gauges carry no samples at
    # all — the same shape as the single-process outage path.
    for absent_name in (
        "incidentrelay_user_notification_deliveries_recent",
        "incidentrelay_alert_notification_errors_recent",
    ):
        family = families.get(absent_name)
        assert family is None or not family.samples, absent_name
    assert (
        sample_value(
            families,
            "incidentrelay_alerts_received_total",
            {"source": "grafana"},
        )
        == 1.0
    )


def test_dead_process_counters_survive_cleanup(tmp_path):
    """
    Counter files of exited processes must survive cleanup: removing one
    would drop its share from the merged counter, and Prometheus would
    read that drop as a counter reset. Only the dead process's live-gauge
    files go.
    """

    # Run a recorder to completion: it exits before any scrape, so its
    # counters survive as a dead process's file.
    _run_child(
        _snippet(_RECORD_ALERTS_AND_EXIT.format(source="grafana")),
        tmp_path,
        _write_child_config(tmp_path),
    )

    dead_files = [
        filename
        for filename in os.listdir(tmp_path)
        if filename.startswith("counter_")
    ]
    dead_files = [
        filename
        for filename in os.listdir(tmp_path)
        if filename.startswith("counter_")
    ]
    assert len(dead_files) == 1
    dead_counter = tmp_path / dead_files[0]
    dead_pid = int(dead_files[0].removeprefix("counter_").removesuffix(".db"))

    # A stale live-gauge file of the same dead process must go.
    dead_gauge = tmp_path / f"gauge_livesum_{dead_pid}.db"
    MmapedDict(str(dead_gauge)).close()

    # A renderer starting now performs the startup cleanup.
    families = parse_exposition(_render(tmp_path))

    assert dead_counter.exists()
    assert not dead_gauge.exists()
    assert (
        sample_value(
            families,
            "incidentrelay_alerts_received_total",
            {"source": "grafana"},
        )
        == 1.0
    )


def test_metrics_view_serves_multiprocess_exposition(client, monkeypatch, tmp_path):
    """
    The view integration: with the multiprocess directory configured the
    endpoint still answers 200 and serves the database gauges even when
    no process has recorded any counter yet.
    """

    from prometheus_client import CONTENT_TYPE_LATEST

    from app.settings import Config

    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    monkeypatch.setattr(Config, "METRICS_ENABLED", True)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.content_type == CONTENT_TYPE_LATEST

    families = parse_exposition(response.get_data())

    assert sample_value(families, "incidentrelay_database_up", {}) == 1.0
    _assert_no_pid_labels(families)


def test_metrics_view_stays_disabled_with_multiproc_dir(client, monkeypatch, tmp_path):
    """Setting the multiprocess directory must not enable the endpoint."""

    from app.settings import Config

    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    monkeypatch.setattr(Config, "METRICS_ENABLED", False)

    assert client.get("/metrics").status_code == 404
    assert client.post("/metrics").status_code == 404


def _init_snippet():
    """Child that imports the collectors and reports success."""

    return (
        "import sys\n"
        f"sys.path.insert(0, {ROOT_DIR!r})\n"
        "import app.services.metrics\n"
        "print('INIT-OK', flush=True)\n"
    )


def test_unusable_multiproc_dir_only_fails_when_metrics_enabled(tmp_path):
    """
    A broken multiproc directory must not block startup while metrics
    are disabled. With metrics enabled it is a deployment error and the
    process refuses to start.
    """

    blocker = tmp_path / "metrics"
    blocker.write_text("occupies the multiproc directory path")

    disabled_config = _write_child_config(tmp_path, enabled=False)
    disabled = subprocess.run(
        [sys.executable, "-c", _init_snippet()],
        env=_child_environment(blocker, disabled_config),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert disabled.returncode == 0, disabled.stderr
    assert "INIT-OK" in disabled.stdout

    enabled_config = _write_child_config(tmp_path, enabled=True)
    enabled = subprocess.run(
        [sys.executable, "-c", _init_snippet()],
        env=_child_environment(blocker, enabled_config),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert enabled.returncode != 0
    assert "not usable" in enabled.stderr


def test_scrape_survives_filesystem_without_flock_support(client, monkeypatch, tmp_path):
    """
    The shared lock is best effort: if the filesystem refuses flock,
    scraping must still work, not fail on every request.
    """

    import app.services.metrics as business_metrics_module
    from app.settings import Config

    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    monkeypatch.setattr(Config, "METRICS_ENABLED", True)

    lockless_fcntl = types.SimpleNamespace(
        LOCK_EX=fcntl.LOCK_EX,
        LOCK_SH=fcntl.LOCK_SH,
        flock=lambda fileno, mode: (_ for _ in ()).throw(
            OSError("filesystem refuses locks"),
        ),
    )
    monkeypatch.setattr(
        business_metrics_module,
        "fcntl",
        lockless_fcntl,
    )

    response = client.get("/metrics")

    assert response.status_code == 200

    families = parse_exposition(response.get_data())
    assert sample_value(families, "incidentrelay_database_up", {}) == 1.0
