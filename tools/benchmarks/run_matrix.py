"""Run reproducible isolated HTTP capacity stages and collect Docker stats."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import threading
import time

COMPOSE = ["docker", "compose", "-p", "ir-capacity-bench", "-f", "tools/benchmarks/compose.yml"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--seconds", type=int, default=15)
    parser.add_argument("--mode", choices=["unique", "repeat", "hot"], action="append")
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 4, 8, 16])
    parser.add_argument("--rate", type=float, nargs="+")
    parser.add_argument("--trace", choices=["full", "compact", "disabled"], default="full")
    parser.add_argument("--pg-cpus", type=float, default=1)
    parser.add_argument("--web-cpus", type=float, default=2)
    parser.add_argument("--async-client", action="store_true")
    parser.add_argument("--request-timeout", type=float, default=20)
    parser.add_argument("--cpu-accounting", action="store_true")
    args = parser.parse_args()
    env = dict(os.environ, BENCH_WORKERS=str(args.workers), BENCH_TRACE_LEVEL=args.trace)
    subprocess.run(COMPOSE + ["up", "-d", "web"], env=env, check=True)
    # Updating the quota in place preserves the disposable tmpfs database.
    subprocess.run(["docker", "update", "--cpus", str(args.pg_cpus), "ir-capacity-bench-postgres-1"], check=True)
    subprocess.run(["docker", "update", "--cpus", str(args.web_cpus), "ir-capacity-bench-web-1"], check=True)
    time.sleep(3)
    results = Path(env.get("BENCH_RESULTS_DIR", "/tmp/ir-capacity-results"))
    results.mkdir(parents=True, exist_ok=True)
    for mode in args.mode or ["unique", "repeat", "hot"]:
        for value in args.rate or args.concurrency:
            concurrency = args.concurrency[0] if args.rate else value
            label = f"w{args.workers}-{mode}-" + (f"r{value}" if args.rate else f"c{value}")
            if args.trace != "full":
                label += "-" + args.trace
            if args.pg_cpus != 1:
                label += f"-pg{args.pg_cpus:g}"
            if args.web_cpus != 2:
                label += f"-web{args.web_cpus:g}"
            label += f"-s{args.seconds}"
            if args.async_client:
                label += "-async"
            command = COMPOSE + ["run", "--rm", "load", "run", "--mode", mode, "--seconds", str(args.seconds),
                                 "--concurrency", str(concurrency), "--label", label]
            if args.rate:
                command += ["--rate", str(value)]
            if args.async_client:
                command += ["--async-client"]
            command += ["--request-timeout", str(args.request_timeout)]
            samples = []
            artifact = label + "-" + str(time.time_ns())
            stop = threading.Event()

            def sample(stop=stop, samples=samples):
                while not stop.is_set():
                    observed = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}",
                                               "ir-capacity-bench-web-1", "ir-capacity-bench-postgres-1"],
                                              capture_output=True, text=True)
                    samples.append({"time": time.time(), "stats": observed.stdout.strip().splitlines()})
                    stop.wait(1)

            monitor = threading.Thread(target=sample)
            monitor.start()

            def cpu_snapshot():
                counters = {}
                for service in ["web", "postgres"]:
                    raw = subprocess.check_output([
                        "docker", "exec", f"ir-capacity-bench-{service}-1", "cat", "/sys/fs/cgroup/cpu.stat",
                    ], text=True)
                    counters[service] = int(dict(line.split() for line in raw.splitlines())["usage_usec"])
                return counters

            try:
                cpu_before = cpu_snapshot() if args.cpu_accounting else None
                completed = subprocess.run(command, env=env, capture_output=True, text=True, check=True)
                (results / f"{artifact}.log").write_text(completed.stdout + completed.stderr)
                print(completed.stdout.strip(), flush=True)
                if args.cpu_accounting:
                    cpu_after = cpu_snapshot()
                    row = next(json.loads(line) for line in reversed(completed.stdout.splitlines()) if line.startswith("{"))
                    web_seconds = (cpu_after["web"]-cpu_before["web"]) / 1_000_000
                    pg_seconds = (cpu_after["postgres"]-cpu_before["postgres"]) / 1_000_000
                    total = web_seconds + pg_seconds
                    events = row["success"]
                    accounting = {
                        "label": label, "run_id": row["run_id"], "events": events,
                        "web_cpu_seconds": round(web_seconds, 6), "postgres_cpu_seconds": round(pg_seconds, 6),
                        "combined_cpu_seconds": round(total, 6),
                        "web_cpu_ms_per_event": round(web_seconds*1000/events, 3) if events else None,
                        "postgres_cpu_ms_per_event": round(pg_seconds*1000/events, 3) if events else None,
                        "combined_cpu_ms_per_event": round(total*1000/events, 3) if events else None,
                        "events_per_combined_cpu_second": round(events/total, 2) if total else None,
                        "target_events_per_combined_cpu_second": 500,
                    }
                    (results / f"{artifact}-cpu.json").write_text(json.dumps(accounting, indent=2)+"\n")
                    with (results / "cpu-accounting.jsonl").open("a") as output:
                        output.write(json.dumps(accounting)+"\n")
                    print("CPU accounting:", json.dumps(accounting), flush=True)
            finally:
                stop.set()
                monitor.join()
                (results / f"{artifact}-stats.json").write_text(json.dumps(samples, indent=2))


if __name__ == "__main__":
    main()
