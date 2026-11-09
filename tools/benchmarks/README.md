# Local PostgreSQL capacity benchmark

This harness runs the checked-out application source, using the published image
only for its Python runtime/dependencies. It creates an isolated Compose project
named `ir-capacity-bench`, with no published ports, no production credentials, no
real notification destinations, and a disposable PostgreSQL database. It does not
use the repository's normal Compose files or existing IncidentRelay containers.

Run commands from the repository root. Docker and Python 3 are required on the
host; Python application dependencies are supplied by the container image.

```sh
mkdir -p /tmp/ir-capacity-results
docker compose -p ir-capacity-bench -f tools/benchmarks/compose.yml run --rm load setup
python3 tools/benchmarks/run_matrix.py --workers 1 --seconds 15
python3 tools/benchmarks/run_matrix.py --workers 4 --seconds 15 --concurrency 4 16
python3 tools/benchmarks/run_matrix.py --workers 4 --pg-cpus 2 --seconds 20 --mode unique --concurrency 32 --rate 10 20 30 40 60
```

`BENCH_RESULTS_DIR` changes the output directory (use an absolute path).
`--trace disabled` or `--trace compact` compares trace settings. PostgreSQL starts
with one CPU; `--pg-cpus` updates its quota in place without losing its database.
The application has two CPUs, 1.5 GiB RAM, and four threads per Gunicorn worker.
The database has 1 GiB RAM. These are benchmark allocations, not recommendations.

**Storage is tmpfs.** This deliberately avoids a disk bottleneck and makes cleanup
simple, but does not measure durable-disk throughput or long-term storage use.
Stopping/recreating the PostgreSQL container destroys the benchmark database;
run `setup` again afterward. Logs are also on tmpfs and are reset on recreation.

## Workloads and interpretation

- `unique`: each request creates an alert and a separate group, using explicit
  `labels.host` grouping. Persisted alerts and distinct groups are independently
  counted after each stage.
- `repeat`: repeated events across 100 fixed identities and groups.
- `hot`: repeated events for one fixed identity and group.

Each HTTP request contains one generic webhook event with route-token
authentication. The final harness opens a fresh HTTP connection for every
request and sends `Connection: close`, avoiding stale Gunicorn keep-alive
sockets. Successful responses must be HTTP 200, report `completed`, and
include a group ID. The fixtures have no rotations, service dependency graphs,
orchestration rules, or notification channels. The scheduler is not running
during intake tests. These tests establish a baseline for this workload, not full
end-to-end production capacity. Repeated/hot stages initially warm their identities;
subsequent stages reuse them. State grows across stages; stage ordering is recorded.

Without `--rate`, clients issue another request after the prior one finishes.
This finds throughput saturation, but masks the impact of a fixed offered load.
With `--rate`, arrivals follow a fixed schedule with bounded in-flight work.
`client_rejected` counts arrivals that exceed that bound; they are load-generator
rejections, not HTTP server errors. Report these alongside HTTP error counts.
`scheduled_p95_ms` includes client dispatch delay. Throughput divides by elapsed
time including final request drain. Percentiles cover dispatched requests only.

Every stage writes an HTTP result to `runs.jsonl` and samples web/database Docker
CPU and memory. CPU 100% means one core. Samples include startup/tail periods, so
do not interpret the raw stage mean as steady-state CPU utilization.

## Profiling and delivery

Run profiling **after** intake tests, so it does not consume database resources
during the measurement. It creates 20 additional unique alerts through Flask's
test client and counts SQL statements. cProfile timings include profiler overhead
and must not be used as HTTP latency measurements.

```sh
docker compose -p ir-capacity-bench -f tools/benchmarks/compose.yml run --rm load profile
docker compose -p ir-capacity-bench -f tools/benchmarks/compose.yml run --rm load idle-worker --seconds 3
```

The delivery probe sends through the actual scheduler notification job to an
in-process localhost HTTP sink. It verifies observed HTTP requests and reports
the job's sent/failed/skipped counts. No external provider is contacted.

```sh
docker compose -p ir-capacity-bench -f tools/benchmarks/compose.yml run --rm load delivery --sink-delay 0
docker compose -p ir-capacity-bench -f tools/benchmarks/compose.yml run --rm load delivery --sink-delay 0.1
docker compose -p ir-capacity-bench -f tools/benchmarks/compose.yml run --rm load delivery --sink-delay 0.5
```

Run delivery **last**: it attaches a local-only channel to the unique route,
clears benchmark pending flags, and schedules the 100 newest unique groups for
each probe. It invokes one batch directly, so its result measures batch service
time. Current PostgreSQL defaults use eight delivery workers and a one-second
tick with batches of 100. SQLite stays serial. The original baseline used one
delivery loop and a ten-second tick; see the historical results and the
[cumulative comparison](IMPROVEMENTS.md). Batch rates do not include waiting for
the next periodic tick or the configured initial group wait.

Cleanup only the benchmark resources:

```sh
docker compose -p ir-capacity-bench -f tools/benchmarks/compose.yml down
```

Raw measurements remain in the output directory. Do not extrapolate short local
runs into production SLOs, large-history behavior, or PostgreSQL concurrency
correctness. Use real PostgreSQL for these measurements, not pgsqlite.

The idle-worker probe calls the real Telegram poller repeatedly with no Telegram
channels, matching the worker's successful-loop behavior. It refuses to run if
any Telegram channel is configured, so it cannot contact Telegram.

## Comparing fixes

See [Python application CPU work](PYTHON-CPU.md) for the subsequent interleaved
comparison of SQL-template reuse and loaded-relationship reuse, with full traces.

```sh
python3 tools/benchmarks/measure_stage.py my-unique-stage-label
python3 tools/benchmarks/render_comparison.py
```

Each stage resets only the benchmark Compose project and initializes a fresh
database, then measures intake, SQL count, idle polling, and delayed delivery.
Use a unique label to preserve previous evidence. The script records the checked
out commit and diff; its label does not switch code versions. To reproduce an
older row, use its recorded source commit in a separate checkout.

Raw stage evidence is copied to `results/improvements/`. PostgreSQL backend IDs
in `profile.json` show physical session reuse across 20 requests. The final
50/sec minute-long probe is stored separately in `results/final-validation/`.
