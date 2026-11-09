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
4. Reuse SQL templates for the route-scoped deduplication and open-group selectors.
5. Refresh dependency correlations once per new alert instead of twice.
6. Skip orchestration state writes when those fields are already persisted.
7. Save only fields modified by group recalculation, preserving unrelated state.

Both template caches are bounded to 256 entries and include database/table layout
in their keys. Neither caches row data. Tests cover fresh values, custom hooks,
expressions, partial updates, rollback, defaults, field conversions and layout
changes, in addition to the lifecycle/concurrency regression suites.

## Comparison per change

The final controlled diagnostic runs eight cumulative variants in one process,
interleaved request by request, reversing their order. Each variant processes
50 unique events per round for four rounds, after warming each variant. All
1,600 measured Alerts and 1,600 completed full traces were counted in PostgreSQL.

| Cumulative Python change | Median app CPU ms/event | Less app CPU vs previous | SQL/event |
|---|---:|---:|---:|
| Ordinary Peewee, after original fixes | 8.012 | — | 59 |
| Reuse primary-key SELECT templates | 7.274 | 9.2% | 59 |
| Also reuse alert INSERT/UPDATE templates | 6.466 | 11.1% | 59 |
| Also retain loaded intake relationships | 6.428 | 0.6% | 58 |
| Also reuse dedup/open-group SELECT templates | 5.976 | 7.0% | 58 |
| Also remove duplicate correlation refresh | 5.868 | 1.8% | 57 |
| Also skip unchanged orchestration state writes | 5.826 | 0.7% | 56 |
| Also save only recalculated group fields | 5.801 | 0.4% | 56 |

The overall app CPU reduction in this run is **27.6%**. Small timing differences
are less reliable than the deterministic reductions: one fewer relationship
SELECT, one fewer correlation SELECT in this fixture, one fewer unchanged UPDATE,
and 18 rather than 59 bound values in the group-recalculation UPDATE. Removing the
duplicate correlation refresh also avoids a second dependency traversal for
service-backed alerts; the small fixture has no service graph.

These are `time.process_time_ns()` measurements around complete processing through
Flask's test client. They include test-client overhead and exclude Gunicorn,
network transport and **PostgreSQL CPU**. They diagnose app work; they do not
establish an HTTP throughput ceiling. Benchmark-only wrappers reproduce former
code paths, including the duplicate refresh and full-row save, and add a small
amount of overhead to those comparison variants.

Absolute timings vary sharply on this shared development machine. Compare
interleaved variants within a run, not absolute numbers from different runs.
For example, the earlier four-variant run measured 21.745 → 17.065 ms/event,
a 21.5% reduction through relationship reuse. That is not an additional speedup
attributable to the later changes. The quieter final run above is the comparison
of all eight variants together.

Raw results and source metadata are retained under `results/08-app-cpu-interleaved/`,
`09-app-cpu-relations/`, `11-select-templates/`, `12-single-correlation-refresh/`,
`13-skip-unchanged-state/`, and `14-derived-fields-only/`.

The subsequent fixes preserve route-scoped deduplication and terminal-state
exclusion, isolate correlation refresh failures, persist preexisting dirty state,
and leave unrelated escalation fields untouched during recalculation. Focused
regression tests cover those behaviors on PostgreSQL and SQLite.

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
`relations` and subsequent variants retain the loaded objects. Those benchmark switches are confined to
the diagnostic process. The real application uses all seven changes. Earlier variants also reproduce the old duplicate refresh, orchestration write and full-row recalculation save; the final `derived-writes` variant uses the complete Python pass.
