"""Report resource experiments separately from code-change comparisons."""
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    cases = [
        ("ceiling-with-telegram", "running", 2),
        ("ceiling-no-telegram-2cpu", "off", 2),
        ("ceiling-no-telegram-3cpu", "off", 3),
        ("ceiling-no-telegram-3cpu-ramp", "off", 3),
    ]
    lines = [
        "# Processing ceiling and local CPU constraints", "",
        "The observed processing plateau rose from roughly 50–60 events/sec with the old Telegram worker",
        "running to roughly 100–105/sec with it stopped and the benchmark web CPU limit raised to three.",
        "All cases use the same processing code, complete full traces, unique alerts/groups, four Gunicorn",
        "workers with four threads each, PostgreSQL limited to two CPUs, and a four-CPU Docker VM.",
        "These are CPU allowances, not dedicated cores. PostgreSQL data/WAL are on tmpfs.", "",
        "## Client constraint removed", "",
        "Arrival-rate probes allow 8,192 in-flight requests, greater than the total offered in each stage.",
        "An asyncio HTTP client avoids thousands of client threads; its timeout is 180 seconds.",
        "Every arrival-rate case below had zero client capacity rejections and zero HTTP/transport errors.",
        "Successful response counts were independently matched to persisted Alerts and distinct AlertGroups.", "",
        "| Telegram worker | Web CPU limit | Offered/sec | Completed/sec during offering | Backlog at end of offer | Drain after offering | HTTP p95 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    saturated = []
    for name, telegram, web_cpus in cases:
        path = root / "results" / name / "runs.jsonl"
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            row = json.loads(line)
            assert row["success"] == row["persisted_unique_alerts"] == row["persisted_unique_groups"]
            assert row["errors"] == row["client_rejected"] == 0
            if not row["offered_rate"]:
                saturated.append((telegram, web_cpus, row))
            elif row["offered_rate"] >= 50:
                lines.append(f"| {telegram} | {web_cpus} | {row['offered_rate']:g} | {row['completion_rate_during_offer']:.2f} | {row['backlog_at_offer_end']} | {row['drain_seconds']:.2f} s | {row['http_p95_ms']:.0f} ms |")
    lines.extend([
        "", "All offer windows above last 20 seconds. Completion rates measure successful events before",
        "that window ends; all remaining requests then drain and are counted/verified separately.",
        "The rows are short probes, not production guarantees. One 100/sec probe processed only 84/sec",
        "during offering, while later 125/150 probes plateaued around 105/sec; run variability is retained.",
        "75/sec completed cleanly with p95 under 200 ms in both Telegram-off resource cases.", "",
        "## Saturation with 128 clients", "",
        "| Telegram worker | Web CPU limit | Completed/sec including drain |",
        "|---|---:|---:|",
    ])
    for telegram, cpus, row in saturated:
        lines.append(f"| {telegram} | {cpus} | {row['success_per_second']:.2f} |")
    lines.extend([
        "", "Removing the old, unused Telegram worker and granting more web CPU materially increases throughput.",
        "The local override makes Telegram opt-in; the core alert service's deployed image was not replaced.",
        "The branch also fixes Telegram's idle busy loop for installations that use that integration.", "",
        "## Combined CPU target", "",
        "The requested target is 500 complete events/sec per combined app + PostgreSQL CPU core:",
        "a budget of 2 CPU milliseconds/event. Throughput divided by allocated cores is not an accurate",
        "CPU efficiency measurement. The CPU-accounting probe sums actual web and PostgreSQL cgroup",
        "usage deltas; load-generator CPU is excluded. PostgreSQL background CPU within the measurement",
        "is included. Later maintenance and production durable-disk behavior are not established here.", "",
    ])
    accounting = root / "results/combined-cpu/cpu-accounting.jsonl"
    if accounting.exists():
        lines.extend(["| Events | Web CPU ms/event | PG CPU ms/event | Combined CPU ms/event | Events/combined CPU second |", "|---:|---:|---:|---:|---:|"])
        for line in accounting.read_text().splitlines():
            row = json.loads(line)
            lines.append(f"| {row['events']} | {row['web_cpu_ms_per_event']:.3f} | {row['postgres_cpu_ms_per_event']:.3f} | {row['combined_cpu_ms_per_event']:.3f} | {row['events_per_combined_cpu_second']:.2f} |")
    lines.extend(["", "Raw evidence and environment settings are under results/ceiling-*/ and results/combined-cpu/.", ""])
    path = root / "CEILING.md"
    path.write_text("\n".join(lines))
    print(path)


if __name__ == "__main__":
    main()
