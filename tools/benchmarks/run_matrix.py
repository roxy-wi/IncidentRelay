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
    args = parser.parse_args()
    env = dict(os.environ, BENCH_WORKERS=str(args.workers), BENCH_TRACE_LEVEL=args.trace)
    subprocess.run(COMPOSE + ["up", "-d", "web"], env=env, check=True)
    # Updating the quota in place preserves the disposable tmpfs database.
    subprocess.run(["docker", "update", "--cpus", str(args.pg_cpus), "ir-capacity-bench-postgres-1"], check=True)
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
            label += f"-s{args.seconds}"
            command = COMPOSE + ["run", "--rm", "load", "run", "--mode", mode, "--seconds", str(args.seconds),
                                 "--concurrency", str(concurrency), "--label", label]
            if args.rate:
                command += ["--rate", str(value)]
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
            try:
                completed = subprocess.run(command, env=env, capture_output=True, text=True, check=True)
                (results / f"{artifact}.log").write_text(completed.stdout + completed.stderr)
                print(completed.stdout.strip(), flush=True)
            finally:
                stop.set()
                monitor.join()
                (results / f"{artifact}-stats.json").write_text(json.dumps(samples, indent=2))


if __name__ == "__main__":
    main()
