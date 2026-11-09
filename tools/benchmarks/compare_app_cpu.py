"""Alternating app-process CPU comparison; excludes PostgreSQL CPU and HTTP server.

Run inside the isolated benchmark load container after setup. Full HTTP handling
uses Flask's test client. This diagnoses Python work, not production capacity.
"""
import argparse
import json
from pathlib import Path
import statistics
import time
import uuid

from peewee import Model

from app import create_app
from app.modules.db import alerts_repo, compiled_select
from app.modules.db.models import Alert, AlertExplainTrace, BaseModel
from tools.benchmarks.capacity import TOKEN, database, payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=50)
    parser.add_argument("--rounds", type=int, default=4)
    args = parser.parse_args()
    if args.events < 1 or args.rounds < 2:
        parser.error("use positive events and at least two alternating rounds")
    db = database()  # Refuses all non-benchmark database names.
    client = create_app().test_client()
    optimized_get = BaseModel.__dict__["get"]
    optimized_save = BaseModel.save
    create_group, create_alert = alerts_repo.create_alert_group, alerts_repo.create_alert
    compiled_first = compiled_select.first
    rows = []

    def scalar_arguments(function):
        def create(**kwargs):
            return function(**{name: value.get_id() if isinstance(value, Model) else value
                               for name, value in kwargs.items()})
        return create

    def select(variant):
        BaseModel.get = classmethod(Model.get.__func__) if variant == "ordinary" else optimized_get
        BaseModel.save = optimized_save if variant in {"lookup-and-writes", "relations", "selectors"} else Model.save
        alerts_repo.create_alert_group = create_group if variant in {"relations", "selectors"} else scalar_arguments(create_group)
        alerts_repo.create_alert = create_alert if variant in {"relations", "selectors"} else scalar_arguments(create_alert)
        compiled_select.first = compiled_first if variant == "selectors" else compiled_select.ordinary_first

    def send(run_id, index):
        response = client.post("/api/integrations/webhook", data=payload(run_id, index, "unique"),
                               headers={"Authorization": "Bearer " + TOKEN + "unique", "Content-Type": "application/json"})
        result = response.get_json()
        if response.status_code != 200 or result[0].get("processing_status") != "completed":
            raise RuntimeError(f"Processing failed: {response.status_code} {result}")

    try:
        for round_number in range(args.rounds):
            variants = ["ordinary", "lookup", "lookup-and-writes", "relations", "selectors"]
            if round_number % 2:
                variants.reverse()
            ids = {variant: uuid.uuid4().hex for variant in variants}
            totals = {variant: [0, 0] for variant in variants}
            for variant in variants:
                select(variant)
                for index in range(5):
                    send("warm-" + ids[variant], index)
            # Interleave variants per event, reversing order each iteration so
            # host drift and database growth do not favor one long block.
            for index in range(args.events):
                order = variants if index % 2 == 0 else list(reversed(variants))
                for variant in order:
                    select(variant)
                    cpu_start, wall_start = time.process_time_ns(), time.monotonic_ns()
                    send(ids[variant], index)
                    totals[variant][0] += time.process_time_ns() - cpu_start
                    totals[variant][1] += time.monotonic_ns() - wall_start
            for variant in variants:
                run_id = ids[variant]
                cpu_ms, wall_ms = (value / 1_000_000 / args.events for value in totals[variant])
                with db.connection_context():
                    persisted = Alert.select().where(Alert.external_id.startswith(run_id)).count()
                    traces = AlertExplainTrace.select().join(Alert).where(
                        Alert.external_id.startswith(run_id), AlertExplainTrace.trace_level == "full",
                        AlertExplainTrace.status == "completed",
                    ).count()
                if persisted != args.events or traces != args.events:
                    raise RuntimeError(f"Missing persisted work: alerts={persisted}, traces={traces}")
                row = dict(round=round_number, variant=variant, events=args.events,
                           app_cpu_ms_per_event=round(cpu_ms, 3), wall_ms_per_event=round(wall_ms, 3),
                           persisted_alerts=persisted, persisted_traces=traces)
                rows.append(row)
                print(json.dumps(row), flush=True)
    finally:
        BaseModel.get = optimized_get
        BaseModel.save = optimized_save
        alerts_repo.create_alert_group, alerts_repo.create_alert = create_group, create_alert
        compiled_select.first = compiled_first
    result = {"scope": "app process incl Flask test client; excludes PG CPU, server and network", "rows": rows,
              "median_app_cpu_ms_per_event": {
                  variant: round(statistics.median(row["app_cpu_ms_per_event"] for row in rows if row["variant"] == variant), 3)
                  for variant in variants}}
    Path("/results/app-cpu-comparison.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["median_app_cpu_ms_per_event"]), flush=True)


if __name__ == "__main__":
    main()
