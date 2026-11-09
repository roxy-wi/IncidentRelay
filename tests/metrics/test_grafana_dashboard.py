"""Check the importable Grafana dashboard against IR and Prometheus."""

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from app.settings import Config
from tests.metrics.exposition import parse_exposition


DASHBOARD = (
    Path(__file__).resolve().parents[2]
    / "tools/grafana/incidentrelay-overview.json"
)


def panel_expressions():
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    return {
        panel["title"]: [target["expr"] for target in panel["targets"]]
        for panel in dashboard["panels"]
        if "targets" in panel
    }


def test_dashboard_uses_exported_metrics(client, monkeypatch):
    """Detect renamed or removed metrics, including sparse DB gauge families."""
    monkeypatch.setattr(Config, "METRICS_ENABLED", True)
    monkeypatch.setattr(Config, "METRICS_AUTH_TOKEN", "")
    response = client.get("/metrics")
    assert response.status_code == 200
    families = parse_exposition(response.data)
    available = set(families)
    for family in families.values():
        if family.type == "counter":
            available.add(family.name + "_total")
        elif family.type == "histogram":
            available.add(family.name + "_bucket")

    expressions = panel_expressions()
    assert expressions
    for panel, targets in expressions.items():
        for expr in targets:
            referenced = set(re.findall(r"\bincidentrelay_\w+", expr))
            assert referenced <= available, (panel, referenced - available)


@pytest.mark.skipif(shutil.which("promtool") is None, reason="promtool not installed")
def test_promql_handles_replicas_and_missing_data(tmp_path):
    """Evaluate the dashboard's actual queries, with Grafana variables expanded."""
    panels = panel_expressions()

    def case(expr, samples):
        return {
            "expr": expr.replace("$job", "web")
            .replace("$instance", "a|b")
            .replace("$__rate_interval", "2m"),
            "eval_time": "6m",
            "exp_samples": [
                {"labels": labels, "value": value} for labels, value in samples
            ],
        }

    def series(metric, instance, values, labels="", job="web"):
        return {
            "series": f'{metric}{{job="{job}",instance="{instance}"{labels}}}',
            "values": values,
        }

    depth = "incidentrelay_user_notification_queue_depth"
    http = "incidentrelay_http_requests_total"
    checks = {
        "Prometheus scrape": [("{}", 0)],
        "Database probe": [("{}", 1)],
        "Pending migrations": [("{}", 2)],
        "Running version": [('{version="2.5.0"}', 1), ('{version="2.5.1"}', 1)],
        "Notification queue depth": [('{state="due"}', 7)],
        "HTTP requests by status": [('{status="200"}', 3)],
        "HTTP 5xx share": [("{}", 0)],
        "Scheduler heartbeat age": [("{}", -1)],
        "Worker heartbeat age": [('{worker="scheduler"}', 60)],
    }
    data = [
        series("up", "a", "1+0x6"),
        series("up", "b", "0+0x6"),
        series("incidentrelay_database_up", "a", "1+0x6"),
        series("incidentrelay_database_up", "b", "1+0x6"),
        series("incidentrelay_migrations_pending", "a", "0+0x6"),
        series("incidentrelay_migrations_pending", "b", "2+0x6"),
        series("incidentrelay_build_info", "a", "1+0x6", ',version="2.5.0"'),
        series("incidentrelay_build_info", "b", "1+0x6", ',version="2.5.1"'),
        series(depth, "a", "7+0x6", ',state="due"'),
        series(depth, "b", "7+0x6", ',state="due"'),
        series(depth, "c", "99+0x6", ',state="due"'),
        series(depth, "a", "99+0x6", ',state="due"', job="other"),
        series(http, "a", "0+60x6", ',status="200",method="GET"'),
        series(http, "b", "0+120x6", ',status="200",method="GET"'),
        series("incidentrelay_scheduler_last_run_timestamp_seconds", "a", "0+0x6"),
        series(
            "incidentrelay_worker_last_seen_timestamp_seconds",
            "a",
            "300+0x6",
            ',worker="scheduler"',
        ),
        series(
            "incidentrelay_worker_last_seen_timestamp_seconds",
            "a",
            "0+0x6",
            ',worker="slack"',
        ),
    ]
    scenarios = [
        {
            "input_series": data,
            "promql_expr_test": [
                case(panels[title][0], expected) for title, expected in checks.items()
            ],
        },
        {
            "input_series": [],
            "promql_expr_test": [
                case(expr, []) for targets in panels.values() for expr in targets
            ],
        },
        {
            # An instant stat can have no current value even though a range
            # query still displays historical points from the same target.
            "input_series": [
                series("up", "a", "1 _x6"),
                series("incidentrelay_database_up", "a", "1 _x6"),
                series("incidentrelay_migrations_pending", "a", "0 _x6"),
                series("incidentrelay_build_info", "a", "1 _x6", ',version="2.5.1"'),
                series("incidentrelay_scheduler_last_run_timestamp_seconds", "a", "1 _x6"),
                series(http, "a", "1 _x6", ',status="200",method="GET"'),
            ],
            "promql_expr_test": [
                case(panels[title][0], [])
                for title in (
                    "Prometheus scrape", "Database probe", "Pending migrations",
                    "Running version", "Scheduler heartbeat age", "HTTP 5xx share",
                )
            ] + [
                {
                    **case(panels["Prometheus scrape"][0], [("{}", 1)]),
                    "eval_time": "0m",
                },
            ],
        },
    ]
    fixture = tmp_path / "dashboard-queries.json"
    fixture.write_text(json.dumps({"evaluation_interval": "1m", "tests": scenarios}))
    subprocess.run(["promtool", "test", "rules", str(fixture)], check=True)
