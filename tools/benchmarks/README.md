# Alert-intake benchmarks

Compare two application revisions under the same workload and resource limits.
The runner measures completed throughput, latency, CPU, memory, backlog, and drain
progress. Each successful request is verified against its persisted alert, group,
completed full trace, and trace steps.

## Requirements

- A Linux or macOS host with Docker's Unix socket available.
- Docker with at least 4 CPUs and enough memory for the isolated services.
- A Python environment with the application and development dependencies installed.
- `uv` for running the chart renderer with Matplotlib.
- Available loopback ports 18380 and 55435.

The benchmark uses disposable PostgreSQL data and synthetic credentials. It does
not use the normal deployment's database or configured notification channels.

## Compare revisions

Choose Git revisions that are available locally. Branches, tags, and commit IDs
are accepted. Export each revision into a separate snapshot directory:

```sh
BASELINE_REF=origin/main
CURRENT_REF=HEAD
BENCH_ROOT=$(mktemp -d)
mkdir -p "$BENCH_ROOT/baseline" "$BENCH_ROOT/current" "$BENCH_ROOT/harness/tools/benchmarks"
git archive "$BASELINE_REF" | tar -x -C "$BENCH_ROOT/baseline"
git archive "$CURRENT_REF" | tar -x -C "$BENCH_ROOT/current"
cp tools/benchmarks/capacity.py tools/benchmarks/benchmark.conf "$BENCH_ROOT/harness/tools/benchmarks/"
docker pull ghcr.io/roxy-wi/incidentrelay:2.5
docker pull postgres:16-alpine
.venv/bin/python tools/benchmarks/run_comparison.py \
  --baseline-ref "$BASELINE_REF" --current-ref "$CURRENT_REF" \
  --root "$BENCH_ROOT" --output "$BENCH_ROOT/run" --seconds 20 --rounds 1
uv run --no-project --with matplotlib python tools/benchmarks/plot_comparison.py \
  "$BENCH_ROOT/run"
```

The runtime image supplies Python dependencies; the exported snapshot supplies
application code. Use `--runtime-image` and `--postgres-image` to select images
compatible with the revisions being compared. Both versions use the same image
IDs throughout a comparison; metadata records the resolved IDs and revisions.

The output directory must not already exist. Snapshots are mounted read-only.
The load generator runs on the host with a raised file-descriptor limit. The
runner checks that Docker resource allocations and container inventory remain
unchanged during measurement.

## Workload and resource settings

Each version uses a fresh PostgreSQL database, four Gunicorn workers with four
threads each, a three-CPU web limit, and a two-CPU PostgreSQL limit. PostgreSQL
data and WAL are on tmpfs, so this workload measures processing rather than
durable-storage performance. Memory measurements include that database storage.

After 125 warmup events, the runner applies fixed-rate loads at 100 and 400
requests/sec, followed by saturation with 128 clients. `--seconds` sets each offer
window. Fixed-rate probes continue until outstanding requests drain, so elapsed
time can exceed the offer window. Compare memory at the same completed request
count rather than at equal wall-clock times.

Telegram is disabled by default. `--include-telegram` additionally runs each
revision's Telegram worker without configured channels or external traffic.
`--rounds` controls repetitions and reverses scenario order on alternating rounds.

## Read and render results

Per-run output includes request summaries and timelines, cumulative CPU counters,
working-set memory samples, PostgreSQL activity, and persistence checks. CPU
boundaries surround HTTP work; the persistence audit runs afterward. Outstanding
requests include client, network, and server waiting, rather than just database
queueing. Drain speed counts successful completions after arrivals stop.

The renderer reads either a run directory or the saved measurement bundle. It
writes throughput/resource charts and a report alongside its inputs. For a run
directory, it selects the first repetition's Telegram-disabled baseline/current
probes; other repetitions remain in the raw output:

```sh
uv run --no-project --with matplotlib python tools/benchmarks/plot_comparison.py \
  tools/benchmarks/results
```

The saved result format uses `measurements.json` for request metrics and timelines,
`metadata.json` for revisions and runtime settings, and compressed resource logs
for cumulative counters. `validation.json` records the associated verification.
