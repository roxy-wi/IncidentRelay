# Cumulative performance fixes

Each stage was measured against a fresh PostgreSQL database using the same commands.
Web: 4 workers × 4 threads, 2 CPU limit. PostgreSQL: 2 CPU limit. Full explain tracing.
Existing containers were left running, including an old Telegram worker consuming a CPU.
Intake excludes the Telegram worker, so changes in its row's intake numbers are run variance.
Short local runs and tmpfs storage do not establish production capacity.

| Cumulative stage | Idle Telegram SQL/sec | SQL/new alert | Saturated new alerts/sec | p95 at 40 offered/sec | Client arrivals not dispatched | Delivery/sec, 100 ms provider | Delivery/sec, 500 ms provider |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 2299.28 | 81 | 32.91 | 889 ms | 0 / 1200 | 8.58 | 1.92 |
| 01-telegram | 1.00 | 81 | 38.69 | 3703 ms | 3 / 1200 | 8.64 | 1.92 |
| 02-sql | 1.00 | 59 | 41.58 | 2890 ms | 64 / 1200 | 8.51 | 1.93 |
| 03-pool | 1.00 | 59 | 63.82 | 30 ms | 0 / 1200 | 8.59 | 1.93 |

The saturation test lasts 20 seconds with 16 concurrent clients. The fixed-rate test offers
40 events/sec for 30 seconds with at most 64 in flight. Client capacity rejections are not
HTTP errors. Every dispatched event was independently checked in PostgreSQL.
Delivery probes use 100 groups at 100 ms delay and 20 groups at 500 ms delay; rates measure
batch execution, not the periodic scheduler's cadence. Idle-worker probes last 3 seconds.
SQL counts include transaction statements routed through Peewee's execute_sql.
Raw JSON, SQL profiles, source commits and diffs are stored under results/improvements/.
See README.md for reproduction; measure_stage.py runs and archives one cumulative stage.
