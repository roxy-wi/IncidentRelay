"""Measure one cumulative code stage on a fresh, isolated PostgreSQL fixture."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from run_matrix import COMPOSE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage")
    parser.add_argument("--output", default="/tmp/ir-perf-comparison")
    args = parser.parse_args()
    output = Path(args.output).resolve() / args.stage
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, BENCH_RESULTS_DIR=str(output), BENCH_WORKERS="4")

    def run(label, command):
        completed = subprocess.run(command, env=env, capture_output=True, text=True)
        (output / (label + ".txt")).write_text(completed.stdout + completed.stderr)
        print(args.stage, label, completed.stdout.strip()[-1600:], flush=True)
        completed.check_returncode()

    run("cleanup", COMPOSE + ["down"])
    run("setup", COMPOSE + ["run", "--rm", "load", "setup"])
    common = [sys.executable, "tools/benchmarks/run_matrix.py", "--workers", "4", "--pg-cpus", "2", "--mode", "unique"]
    run("saturation", common + ["--seconds", "20", "--concurrency", "16"])
    run("fixed-rate", common + ["--seconds", "30", "--concurrency", "64", "--rate", "40"])
    for label, command in [
        ("profile", ["profile"]),
        ("idle-worker", ["idle-worker", "--seconds", "3"]),
        ("delivery-100ms", ["delivery", "--sink-delay", "0.1"]),
        ("delivery-500ms", ["delivery", "--sink-delay", "0.5", "--batch-size", "20"]),
    ]:
        run(label, COMPOSE + ["run", "--rm", "load"] + command)
    (output / "source.json").write_text(json.dumps({
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "diff": subprocess.check_output(["git", "diff"], text=True),
        "stage": args.stage,
    }, indent=2))
    destination = Path("tools/benchmarks/results/improvements") / args.stage
    destination.mkdir(parents=True, exist_ok=True)
    for name in ["runs.jsonl", "delivery.jsonl", "idle-worker.json", "profile.txt", "profile.json", "source.json"]:
        shutil.copyfile(output / name, destination / name)
    run("cleanup-final", COMPOSE + ["down"])
    print("Saved", destination, flush=True)


if __name__ == "__main__":
    main()
