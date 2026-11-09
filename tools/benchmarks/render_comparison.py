"""Render the cumulative measurements without treating run variance as causation."""
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    stages = root / "results/improvements"
    lines = [
        "# Cumulative performance fixes", "",
        "Each stage was measured against a fresh PostgreSQL database using the same commands.",
        "Web: 4 workers × 4 threads, 2 CPU limit. PostgreSQL: 2 CPU limit. Full explain tracing.",
        "Existing containers were left running, including an old Telegram worker consuming a CPU.",
        "Intake excludes Telegram and scheduler workers; intake differences after their fixes are run variance.",
        "Short local runs and tmpfs storage do not establish production capacity.", "",
        "| Cumulative stage | Idle Telegram SQL/sec | SQL/new alert | Saturated new alerts/sec | p95 at 40 offered/sec | Client arrivals not dispatched | Delivery/sec, 100 ms provider | Delivery/sec, 500 ms provider |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for directory in sorted([path for path in stages.iterdir() if path.is_dir()], key=lambda p: (p.name != "baseline", p.name)):
        rows = [json.loads(line) for line in (directory / "runs.jsonl").read_text().splitlines()]
        saturated = next(row for row in rows if not row["offered_rate"])
        fixed = next(row for row in rows if row["offered_rate"])
        for row in rows:
            assert row["success"] == row["persisted_unique_alerts"] == row["persisted_unique_groups"]
            assert row["errors"] == 0
        profile = json.loads((directory / "profile.json").read_text())
        idle = json.loads((directory / "idle-worker.json").read_text())
        deliveries = [json.loads(line) for line in (directory / "delivery.jsonl").read_text().splitlines()]
        fast = next(row for row in deliveries if row["sink_delay_seconds"] == 0.1)
        slow = next(row for row in deliveries if row["sink_delay_seconds"] == 0.5)
        assert all(row["sent"] == row["processed"] == row["observed_http_deliveries"] and not row["failed"] for row in deliveries)
        sql = sum(profile["counts"].values()) / profile["requests"]
        lines.append(f"| {directory.name} | {idle['sql_per_second']:.2f} | {sql:g} | {saturated['success_per_second']:.2f} | {fixed['http_p95_ms']:.0f} ms | {fixed['client_rejected']} / {fixed['offered']} | {fast['deliveries_per_second']:.2f} | {slow['deliveries_per_second']:.2f} |")
    lines.extend([
        "", "The saturation test lasts 20 seconds with 16 concurrent clients. The fixed-rate test offers",
        "40 events/sec for 30 seconds with at most 64 in flight. Client capacity rejections are not",
        "HTTP errors. Every dispatched event was independently checked in PostgreSQL.",
        "Delivery probes use 100 groups at 100 ms delay and 20 groups at 500 ms delay; rates measure",
        "batch execution, not the periodic scheduler's cadence. Idle-worker probes last 3 seconds.",
        "SQL counts include transaction statements routed through Peewee's execute_sql.",
        "Raw JSON, SQL profiles, source commits and diffs are stored under results/improvements/.",
        "See README.md for reproduction; measure_stage.py runs and archives one cumulative stage.", "",
    ])
    connection_counts = []
    for stage in ["02-sql", "03-pool", "04-delivery"]:
        path = stages / stage / "profile.json"
        if path.exists():
            profile = json.loads(path.read_text())
            connection_counts.append(f"{stage}: {profile.get('postgres_backends_used', 'not recorded')}")
    if connection_counts:
        lines.extend(["PostgreSQL physical backends used by each 20-request profile: " + "; ".join(connection_counts) + ".", ""])
    validation_path = root / "results/final-validation/runs.jsonl"
    if validation_path.exists():
        validation = json.loads(validation_path.read_text().splitlines()[-1])
        assert validation["success"] == validation["persisted_unique_alerts"] == validation["persisted_unique_groups"]
        lines.extend([
            "## Earlier 50/sec check with Telegram still running", "",
            f"The final code was offered {validation['offered']} unique events over {validation['seconds']:g} seconds.",
            f"It persisted {validation['success']}, with {validation['errors']} HTTP/client transport errors and {validation['client_rejected']} arrivals not dispatched at the 64-request client limit.",
            f"Throughput including drain was {validation['success_per_second']:.2f}/sec; p95 was {validation['http_p95_ms']:.0f} ms and p99 {validation['http_p99_ms']:.0f} ms.",
            "This was the earlier environment's edge. Later probes remove the client cap and stop the unused Telegram worker; see CEILING.md.", "",
        ])
    path = root / "IMPROVEMENTS.md"
    path.write_text("\n".join(lines))
    print(path.read_text())


if __name__ == "__main__":
    main()
