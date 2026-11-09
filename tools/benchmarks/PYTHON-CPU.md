# Python application CPU work

Python remains the implementation language. These changes follow the original
[intake/delivery fixes](IMPROVEMENTS.md); no schema changes were made.

1. Cache scalar primary-key SELECT SQL templates, while binding current values
   and hydrating fresh database rows on every call. Custom queries fall back.
2. Cache ordinary INSERT/UPDATE SQL templates for five explicitly opted-in alert
   models. Field conversion, dirty fields, transactions, generated IDs and hooks
   retain their normal behavior. Unsupported inputs use Peewee's normal save.
3. Pass already loaded models into new Alert/AlertGroup foreign keys. Peewee can
   reuse those objects during the request instead of fetching them again.

Both template caches are bounded to 256 entries and include database/table layout
in their keys. Neither caches row data. Tests cover fresh values, custom hooks,
expressions, partial updates, rollback, defaults, field conversions and layout
changes, in addition to the lifecycle/concurrency regression suites.

## Comparison per change

The controlled diagnostic runs all four variants in one process, interleaved
request by request, reversing their order. Each variant processes 50 unique events
per round, four rounds, after warming each variant. All 800 measured Alerts and
800 completed full traces were independently counted in PostgreSQL.

| Cumulative Python change | Median app CPU ms/event | Less app CPU vs previous | SQL/event |
|---|---:|---:|---:|
| Ordinary Peewee, after original fixes | 21.745 | — | 59 |
| Reuse primary-key SELECT templates | 20.165 | 7.3% | 59 |
| Also reuse alert INSERT/UPDATE templates | 17.476 | 13.3% | 59 |
| Also retain loaded intake relationships | 17.065 | 2.4% | 58 |

The overall reduction in this run is **21.5%**. The relationship change was small:
two rounds were slightly slower, two faster; its deterministic improvement is one
fewer SELECT/event. Before that change, a separate three-variant interleaved run
measured 16.711 → 15.332 → 13.476 app CPU ms/event, a 19.4% overall reduction.

These are `time.process_time_ns()` measurements around complete processing through
Flask's test client. They include test-client overhead and exclude Gunicorn,
network transport and **PostgreSQL CPU**. They diagnose app work; they do not
establish a production throughput ceiling or the combined CPU target.

Absolute CPU timings vary sharply on this shared development machine. Compare
interleaved variants within a run, not absolute numbers from different runs.
Raw results, per-round values and source metadata are in
`results/08-app-cpu-interleaved/` and `results/09-app-cpu-relations/`.

## Container A/B results retained

The earlier end-to-end measurements use four Gunicorn workers, four threads each,
web allowance three CPUs, PostgreSQL allowance two CPUs, and a shared four-CPU
Docker VM. PostgreSQL storage is tmpfs. Each row offers 800 unique events over
20 seconds at 40/sec with full traces and an 8,192-request client allowance.
All rows persisted 800 Alerts and groups without errors or client rejections.

| Write templates | App CPU ms/event | PG CPU ms/event | Combined CPU ms/event |
|---|---:|---:|---:|
| Off A | 24.894 | 16.414 | 41.309 |
| On A | 18.199 | 11.483 | 29.683 |
| Off B | 23.958 | 14.146 | 38.104 |
| On B | 37.811 | 25.568 | 63.379 |

This sequence does **not** demonstrate an end-to-end speedup: both app and PG CPU
drift considerably despite identical SQL counts. It motivated the interleaved
app-process diagnostic above. Raw results are retained in `results/07-write-*/`.
Earlier lookup-only A/B results and the exploratory unpaired measurement are also
retained; the exploratory result is not used to claim a speedup.

The user clarified the current target as **500 completed requests/sec total**.
The earlier CPU-normalized target in [CEILING.md](CEILING.md) is historical.
App CPU cost alone does not establish aggregate HTTP throughput: that requires
the complete server/database capacity probe. The earlier observed ceiling of
about 103/sec applies to the earlier code/environment and must not be relabeled
as a measurement of these changes.

## Reproduce the controlled app diagnostic

Use only the disposable benchmark project. Do not run performance measurements
alongside regression suites or other capacity probes.

```sh
export BENCH_RESULTS_DIR=/tmp/ir-python-cpu-reproduction
docker compose -p ir-capacity-bench -f tools/benchmarks/compose.yml down
docker compose -p ir-capacity-bench -f tools/benchmarks/compose.yml run --rm load setup
docker compose -p ir-capacity-bench -f tools/benchmarks/compose.yml run --rm \
  --entrypoint python load tools/benchmarks/compare_app_cpu.py --events 50 --rounds 4
docker compose -p ir-capacity-bench -f tools/benchmarks/compose.yml run --rm load profile
docker compose -p ir-capacity-bench -f tools/benchmarks/compose.yml down
```

The diagnostic's `ordinary`, `lookup`, and `lookup-and-writes` variants convert
creation arguments back to scalar IDs to emulate the earlier intake behavior.
`relations` retains the loaded objects. Those benchmark switches are confined to
the diagnostic process. The real application uses all three changes.
