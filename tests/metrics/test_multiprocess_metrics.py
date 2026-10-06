"""
Cross-process aggregation tests for the multiprocess metrics mode.

prometheus_client chooses its value class from the environment at first
import, so a pytest process that already imported the collectors cannot
exercise the multiprocess path by flipping environment variables. These
tests therefore drive real subprocesses: recorder children record events
with PROMETHEUS_MULTIPROC_DIR set (they stand in for the scheduler and
the Telegram/Slack daemons and for sibling Gunicorn workers), a renderer
child produces the exposition through render_exposition(), and the
pytest process parses and asserts on the output — the same split as a
real deployment, where one web worker scrapes while every process
records. Recorders stay alive while the scrape runs, mirroring the
long-lived daemons of a real deployment; the exit-cleanup test covers
the short-lived case separately.
"""

import base64
import os
import subprocess
import sys
import textwrap
from contextlib import contextmanager

from prometheus_client.mmap_dict import MmapedDict
from prometheus_client.parser import text_string_to_metric_families

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

_ENABLE_CONFIG = """
    from app.settings import Config
    Config.METRICS_ENABLED = True
"""

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


def _snippet(body):
    """Wrap a snippet with the imports every child needs."""

    return (
        "import sys\n"
        f"sys.path.insert(0, {ROOT_DIR!r})\n"
        f"{textwrap.dedent(_ENABLE_CONFIG).strip()}\n"
        f"{textwrap.dedent(body).strip()}\n"
    )


def _child_environment(multiproc_dir):
    environment = os.environ.copy()
    environment["PROMETHEUS_MULTIPROC_DIR"] = str(multiproc_dir)
    environment["PYTHONPATH"] = os.pathsep.join(
        [ROOT_DIR, environment.get("PYTHONPATH", "")],
    )

    return environment


def _run_child(code, multiproc_dir):
    """Run one child process with the multiprocess directory configured."""

    return subprocess.run(
        [sys.executable, "-c", code],
        env=_child_environment(multiproc_dir),
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )


@contextmanager
def _live_recorder(code, multiproc_dir):
    """
    Run a recorder child that stays alive until the block ends.

    The child records, signals READY and then blocks; closing our end of
    its stdin stops it. If it dies before READY (import error, crash),
    the assertion surfaces its stderr instead of a confusing KeyError.
    """

    process = subprocess.Popen(
        [sys.executable, "-c", code],
        env=_child_environment(multiproc_dir),
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
    )


def _record_action(multiproc_dir, action="resolved"):
    return _live_recorder(
        _snippet(_RECORD_ACTION.format(action=action)),
        multiproc_dir,
    )


def _render(multiproc_dir, setup=""):
    """Render the exposition in a fresh child process; return the body."""

    result = _run_child(
        _snippet(setup + _RENDER),
        multiproc_dir,
    )

    return base64.b64decode(result.stdout)


def _parse(body):
    """Parse an exposition into a name -> family mapping."""

    families = {}

    for family in text_string_to_metric_families(body.decode()):
        families[family.name] = family

    return families


def _sample_value(families, name, labels):
    """Latest value of one sample across all families (None when absent).

    Lookup goes by sample name: the text parser names counter families
    without the ``_total`` suffix the samples carry.
    """

    value = None

    for family in families.values():
        for sample in family.samples:
            if sample.name == name and sample.labels == labels:
                value = sample.value

    return value


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
        families = _parse(_render(tmp_path))

    assert (
        _sample_value(
            families,
            "incidentrelay_alerts_received_total",
            {"source": "grafana"},
        )
        == 3.0
    )
    assert (
        _sample_value(
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
        families = _parse(_render(tmp_path))

    assert (
        _sample_value(
            families,
            "incidentrelay_alert_group_actions_total",
            {"action": "resolved"},
        )
        == 1.0
    )


def test_scrape_reflects_events_recorded_between_scrapes(tmp_path):
    """Two scrapes must behave like Prometheus scraping twice: grow."""

    with _record_alerts(tmp_path, count=2) as first_recorder:
        first = _parse(_render(tmp_path))

        with _record_alerts(tmp_path, count=2):
            second = _parse(_render(tmp_path))

    del first_recorder

    first_value = _sample_value(
        first,
        "incidentrelay_alerts_received_total",
        {"source": "grafana"},
    )
    second_value = _sample_value(
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
        families = _parse(_render(tmp_path))

    assert len(families["incidentrelay_database_up"].samples) == 1
    assert len(families["incidentrelay_build_info"].samples) == 1
    assert len(families["incidentrelay_scheduler_last_run_timestamp_seconds"].samples) == 1
    assert _sample_value(families, "incidentrelay_database_up", {}) == 1.0
    _assert_no_pid_labels(families)


def test_database_outage_degrades_gauges_in_multiprocess_mode(tmp_path):
    """
    Same outage contract as single-process mode: database_up 0, absent
    delivery gauges, heartbeat 0, and the exposition still renders.
    """

    with _record_alerts(tmp_path, count=1):
        families = _parse(_render(tmp_path, setup=_BREAK_DATABASE))

    assert _sample_value(families, "incidentrelay_database_up", {}) == 0.0
    assert (
        _sample_value(
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
        _sample_value(
            families,
            "incidentrelay_alerts_received_total",
            {"source": "grafana"},
        )
        == 1.0
    )


def test_dead_process_files_are_removed_at_next_process_start(tmp_path):
    """
    Files of exited processes keep contributing until the next
    IncidentRelay process starts: a renderer started afterwards removes
    the dead process's file, while files of live processes (here: the
    pytest process itself) survive.
    """

    # Run a recorder to completion: it exits before any scrape, so its
    # counters survive as a dead process's file.
    _run_child(
        _snippet(_RECORD_ALERTS_AND_EXIT.format(source="grafana")),
        tmp_path,
    )

    dead_files = [
        filename
        for filename in os.listdir(tmp_path)
        if filename.startswith("counter_")
    ]
    assert len(dead_files) == 1
    dead_file = tmp_path / dead_files[0]

    live_file = tmp_path / f"counter_{os.getpid()}.db"
    MmapedDict(str(live_file)).close()

    # A renderer starting now performs the startup cleanup.
    _render(tmp_path)

    assert not dead_file.exists()
    assert live_file.exists()


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

    families = _parse(response.get_data())

    assert _sample_value(families, "incidentrelay_database_up", {}) == 1.0
    _assert_no_pid_labels(families)


def test_metrics_view_stays_disabled_with_multiproc_dir(client, monkeypatch, tmp_path):
    """Setting the multiprocess directory must not enable the endpoint."""

    from app.settings import Config

    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    monkeypatch.setattr(Config, "METRICS_ENABLED", False)

    assert client.get("/metrics").status_code == 404
    assert client.post("/metrics").status_code == 404
