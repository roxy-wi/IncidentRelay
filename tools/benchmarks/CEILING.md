# Processing ceiling and local CPU constraints

This records the earlier checkpoint. See [the completed Python pass](PYTHON-CPU.md)
for the latest measured 261/sec saturation result and the 500/sec overload probe.
The current target is 500 completed requests/sec total; the per-core target below
is historical.

The observed processing plateau rose from roughly 50–60 events/sec with the old Telegram worker
running to roughly 100–105/sec with it stopped and the benchmark web CPU limit raised to three.
All cases use the same processing code, complete full traces, unique alerts/groups, four Gunicorn
workers with four threads each, PostgreSQL limited to two CPUs, and a four-CPU Docker VM.
These are CPU allowances, not dedicated cores. PostgreSQL data/WAL are on tmpfs.

## Client constraint removed

Arrival-rate probes allow 8,192 in-flight requests, greater than the total offered in each stage.
An asyncio HTTP client avoids thousands of client threads; its timeout is 180 seconds.
Every arrival-rate case below had zero client capacity rejections and zero HTTP/transport errors.
Successful response counts were independently matched to persisted Alerts and distinct AlertGroups.

| Telegram worker | Web CPU limit | Offered/sec | Completed/sec during offering | Backlog at end of offer | Drain after offering | HTTP p95 |
|---|---:|---:|---:|---:|---:|---:|
| running | 2 | 50 | 49.95 | 1 | 0.01 s | 361 ms |
| running | 2 | 75 | 53.65 | 427 | 7.81 s | 8471 ms |
| running | 2 | 100 | 58.70 | 826 | 14.73 s | 14930 ms |
| running | 2 | 150 | 42.10 | 2158 | 36.76 s | 36160 ms |
| off | 2 | 50 | 49.95 | 1 | 0.01 s | 38 ms |
| off | 2 | 75 | 74.95 | 1 | 0.01 s | 41 ms |
| off | 3 | 50 | 48.85 | 23 | 0.54 s | 52 ms |
| off | 3 | 75 | 74.95 | 1 | 0.01 s | 186 ms |
| off | 3 | 100 | 83.80 | 324 | 3.23 s | 4158 ms |
| off | 3 | 125 | 105.05 | 399 | 3.77 s | 4002 ms |
| off | 3 | 150 | 104.80 | 904 | 8.98 s | 8454 ms |

All offer windows above last 20 seconds. Completion rates measure successful events before
that window ends; all remaining requests then drain and are counted/verified separately.
The rows are short probes, not production guarantees. One 100/sec probe processed only 84/sec
during offering, while later 125/150 probes plateaued around 105/sec; run variability is retained.
75/sec completed cleanly with p95 under 200 ms in both Telegram-off resource cases.

## Saturation with 128 clients

| Telegram worker | Web CPU limit | Completed/sec including drain |
|---|---:|---:|
| running | 2 | 52.51 |
| off | 2 | 82.10 |
| off | 3 | 102.58 |

Removing the old, unused Telegram worker and granting more web CPU materially increases throughput.
The local override makes Telegram opt-in; the core alert service's deployed image was not replaced.
The branch also fixes Telegram's idle busy loop for installations that use that integration.

## Combined CPU target

The requested target is 500 complete events/sec per combined app + PostgreSQL CPU core:
a budget of 2 CPU milliseconds/event. Throughput divided by allocated cores is not an accurate
CPU efficiency measurement. The CPU-accounting probe sums actual web and PostgreSQL cgroup
usage deltas; load-generator CPU is excluded. PostgreSQL background CPU within the measurement
is included. Later maintenance and production durable-disk behavior are not established here.

| Events | Web CPU ms/event | PG CPU ms/event | Combined CPU ms/event | Events/combined CPU second |
|---:|---:|---:|---:|---:|
| 800 | 19.963 | 11.155 | 31.118 | 32.14 |
| 2000 | 33.250 | 18.359 | 51.609 | 19.38 |

Raw evidence and environment settings are under results/ceiling-*/ and results/combined-cpu/.
