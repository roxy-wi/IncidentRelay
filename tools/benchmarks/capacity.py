"""Actual HTTP intake load, with response validation and bounded open-loop load.

Run only with tools/benchmarks/compose.yml: setup refuses other database names.
No external notification channels are configured by setup.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import cProfile
import hashlib
import http.client
import json
from pathlib import Path
import pstats
import threading
import time
import uuid

TOKEN = "isolated-capacity-benchmark-token"


def database():
    from app.db import init_database
    db = init_database()
    if db.database != "ir_capacity_bench":
        raise RuntimeError("Refusing to benchmark a non-benchmark database")
    db.connect(reuse_if_open=True)
    return db


def setup():
    db = database()
    from app.modules.db.migrations import migrate
    from app.modules.db.models import Group, Team, AlertRoute
    migrate()
    db.execute_sql("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
    group, _ = Group.get_or_create(slug="capacity-bench", defaults={"name": "Capacity benchmark", "active": True})
    team, _ = Team.get_or_create(slug="capacity-bench", defaults={"group": group, "name": "Capacity benchmark", "active": True})
    for mode in ("unique", "repeat", "hot"):
        AlertRoute.get_or_create(name="bench-" + mode, defaults={
            "team": team, "source": "webhook", "enabled": True,
            "matchers": {}, "group_by": ["labels.host"],
            "intake_token_prefix": mode,
            "intake_token_hash": hashlib.sha256((TOKEN + mode).encode()).hexdigest(),
        })
        AlertRoute.update(group_by=["labels.host"]).where(AlertRoute.name == "bench-" + mode).execute()
    print(json.dumps({"setup": "ok", "database": db.database}))


def payload(run_id, index, mode):
    key = f"{run_id}-{index}" if mode == "unique" else f"bench-{mode}-{index % (100 if mode == 'repeat' else 1)}"
    return json.dumps({"title": "Capacity benchmark", "message": "Local synthetic test; no external delivery.",
                       "severity": "critical", "status": "firing", "fingerprint": key,
                       "external_id": key, "labels": {"environment": "benchmark", "host": key}}).encode()


def request(run_id, index, mode, scheduled=None):
    started = time.monotonic()
    scheduled = started if scheduled is None else scheduled
    connection = http.client.HTTPConnection("web", 8080, timeout=20)
    try:
        connection.request("POST", "/api/integrations/webhook", body=payload(run_id, index, mode),
                           headers={"Authorization": "Bearer " + TOKEN + mode, "Content-Type": "application/json", "Connection": "close"})
        response = connection.getresponse()
        raw = response.read()
        result = json.loads(raw)
        ok = response.status == 200 and isinstance(result, list) and len(result) == 1 and bool(result[0].get("group_id")) and result[0].get("processing_status") == "completed"
        detail = "ok" if ok else f"HTTP {response.status}: {raw[:350].decode(errors='replace')}"
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        ok = False
    finally:
        connection.close()
    ended = time.monotonic()
    return ok, ended - started, ended - scheduled, started - scheduled, detail


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values)-1, int((len(values)-1)*fraction))] * 1000, 2)


def run(args):
    run_id = uuid.uuid4().hex[:12]
    started = time.monotonic()
    stop = started + args.seconds
    results = []
    rejected = 0
    offered = 0
    result_lock = threading.Lock()

    def closed(worker):
        values = []
        index = worker
        while time.monotonic() < stop:
            values.append(request(run_id, index, args.mode))
            index += args.concurrency
        return values

    def done(future):
        with result_lock:
            results.append(future.result())
        slots.release()

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        if args.rate:
            # No unbounded executor queue. Latency includes scheduling and dispatch
            # delay, so overload is not hidden by a closed-loop client.
            slots = threading.BoundedSemaphore(args.concurrency)
            while True:
                scheduled = started + offered / args.rate
                if scheduled >= stop:
                    break
                delay = scheduled - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                if slots.acquire(blocking=False):
                    pool.submit(request, run_id, offered, args.mode, scheduled).add_done_callback(done)
                else:
                    rejected += 1
                offered += 1
        else:
            futures = [pool.submit(closed, worker) for worker in range(args.concurrency)]
            for future in futures:
                results.extend(future.result())
            offered = len(results)
    elapsed = time.monotonic() - started
    good = [r for r in results if r[0]]
    record = {"run_id": run_id, "label": args.label, "mode": args.mode, "seconds": args.seconds,
              "transport": "connection-close",
              "concurrency": args.concurrency, "offered_rate": args.rate,
              "elapsed_seconds": round(elapsed, 3), "offered": offered, "completed": len(results),
              "success": len(good), "errors": len(results)-len(good), "client_rejected": rejected,
              "success_per_second": round(len(good)/elapsed, 2),
              "http_p50_ms": percentile([r[1] for r in results], .5),
              "http_p95_ms": percentile([r[1] for r in results], .95),
              "http_p99_ms": percentile([r[1] for r in results], .99),
              "scheduled_p95_ms": percentile([r[2] for r in results], .95),
              "dispatch_p95_ms": percentile([r[3] for r in results], .95),
              "failures": dict(Counter(r[4] for r in results if not r[0]))}
    db = database()
    if args.mode == "unique":
        # Independently confirm reported successes were actually persisted.
        from app.modules.db.models import Alert
        record["persisted_unique_alerts"] = Alert.select().where(Alert.external_id.startswith(run_id + "-")).count()
        record["persisted_unique_groups"] = Alert.select(Alert.group).where(Alert.external_id.startswith(run_id + "-")).distinct().count()
    else:
        from app.modules.db.models import Alert, AlertRoute
        route = AlertRoute.get(AlertRoute.name == "bench-" + args.mode)
        record["persisted_identity_count"] = Alert.select().where(Alert.route == route).count()
        record["persisted_group_count"] = Alert.select(Alert.group).where(Alert.route == route).distinct().count()
    record["database_bytes"] = db.execute_sql("SELECT pg_database_size(current_database())").fetchone()[0]
    print(json.dumps(record), flush=True)
    with Path("/results/runs.jsonl").open("a") as output:
        output.write(json.dumps(record) + "\n")


def profile():
    from app import create_app
    db = database()
    client = create_app().test_client()
    counts = Counter()
    original = db.execute_sql

    def execute(sql, params=None, *a, **kw):
        counts[sql.split()[0].upper()] += 1
        return original(sql, params, *a, **kw)

    db.execute_sql = execute
    profiler = cProfile.Profile()
    profiler.enable()
    statuses = []
    for i in range(20):
        response = client.post("/api/integrations/webhook", data=payload(uuid.uuid4().hex, i, "unique"),
                               headers={"Authorization": "Bearer " + TOKEN + "unique", "Content-Type": "application/json"})
        statuses.append(response.status_code)
    profiler.disable()
    print("SQL statements / 20 requests:", dict(counts), "HTTP statuses:", dict(Counter(statuses)))
    pstats.Stats(profiler).strip_dirs().sort_stats("cumulative").print_stats(30)


def delivery(args):
    """Measure the real delivery loop against a local, controlled HTTP sink."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from app import create_app
    from app.modules.common import utc_now
    from app.modules.db.models import AlertGroup, AlertRoute, AlertRouteChannel, NotificationChannel
    from app.services.scheduler import alert_group_notification_job
    from app.settings import Config
    db = database()
    Config.OUTBOUND_HTTP_PRIVATE_NETWORK_ALLOWLIST = "127.0.0.1/32"
    observed = []

    class Sink(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            time.sleep(args.sink_delay)
            observed.append(time.monotonic())
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *unused):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 9090), Sink)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    route = AlertRoute.get(AlertRoute.name == "bench-unique")
    channel, _ = NotificationChannel.get_or_create(name="benchmark-local-sink", defaults={
        "group": route.team.group, "team": route.team, "channel_type": "webhook", "enabled": True,
        "config": {"webhook_url": "http://127.0.0.1:9090/"},
    })
    AlertRouteChannel.get_or_create(route=route, channel=channel)
    # Only the isolated benchmark DB is allowed by database(). No real channels.
    AlertGroup.update(notification_pending=False).execute()
    ids = [g.id for g in AlertGroup.select(AlertGroup.id).where(AlertGroup.route == route).order_by(AlertGroup.id.desc()).limit(args.batch_size)]
    if len(ids) != args.batch_size:
        raise RuntimeError("Run unique intake first to create enough delivery fixtures")
    AlertGroup.update(notification_pending=True, notification_due_at=utc_now(),
                      notification_reason="initial", last_notification_at=None).where(AlertGroup.id.in_(ids)).execute()
    app = create_app(log_role="scheduler")
    started = time.monotonic()
    with app.app_context():
        result = alert_group_notification_job()
    elapsed = time.monotonic() - started
    result.update({"action": "delivery", "sink_delay_seconds": args.sink_delay, "elapsed_seconds": round(elapsed, 3),
                   "observed_http_deliveries": len(observed), "deliveries_per_second": round(len(observed)/elapsed, 2)})
    print(json.dumps(result), flush=True)
    with Path("/results/delivery.jsonl").open("a") as output:
        output.write(json.dumps(result) + "\n")
    server.shutdown()


def idle_worker(args):
    """Reproduce idle Telegram polling using only the isolated empty fixture."""
    from app.notifiers.telegram.poller import list_polling_telegram_channels, poll_telegram_channels_once
    db = database()
    if list_polling_telegram_channels():
        raise RuntimeError("Idle probe requires zero Telegram channels; refusing network calls")
    sql_count = 0
    original = db.execute_sql

    def execute(sql, params=None, *a, **kw):
        nonlocal sql_count
        sql_count += 1
        return original(sql, params, *a, **kw)

    db.execute_sql = execute
    started = time.monotonic()
    cpu_started = time.process_time()
    iterations = 0
    while time.monotonic() - started < args.seconds:
        poll_telegram_channels_once(timeout=20)
        iterations += 1
    elapsed = time.monotonic() - started
    record = {"action": "idle_worker", "elapsed_seconds": round(elapsed, 3), "iterations": iterations,
              "sql_statements": sql_count, "sql_per_second": round(sql_count/elapsed, 2),
              "python_cpu_seconds": round(time.process_time()-cpu_started, 3)}
    print(json.dumps(record))
    Path("/results/idle-worker.json").write_text(json.dumps(record, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["setup", "run", "profile", "delivery", "idle-worker"])
    parser.add_argument("--mode", choices=["unique", "repeat", "hot"], default="unique")
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--rate", type=float, default=0)
    parser.add_argument("--label", default="")
    parser.add_argument("--sink-delay", type=float, default=0)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    if args.seconds <= 0 or args.concurrency < 1 or args.rate < 0:
        parser.error("seconds and concurrency must be positive; rate must be nonnegative")
    {"setup": setup, "run": lambda: run(args), "profile": profile,
     "delivery": lambda: delivery(args), "idle-worker": lambda: idle_worker(args)}[args.action]()
