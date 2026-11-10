"""Run immutable baseline/current app snapshots under identical benchmark settings.

Uses immutable source/harness snapshots under --root. It never changes unrelated
containers. Host-side load generation does not compete inside the Docker VM.
"""
import argparse
import fcntl
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import resource
import socket
import subprocess
import sys
import threading
import time

import psycopg2


PROJECT = "ir-intake-bench"
COMPOSE = ["docker", "compose", "-p", PROJECT, "--profile", "telegram", "-f", str(Path(__file__).with_name("compose.yml"))]


class DockerConnection(HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=15)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def docker_api(path):
    connection = DockerConnection(SOCKET)
    try:
        connection.request("GET", "/v1.45" + path)
        response = connection.getresponse()
        data = json.loads(response.read())
        if response.status != 200:
            raise RuntimeError(data)
        return data
    finally:
        connection.close()


def inventory():
    result = {}
    for container in docker_api("/containers/json"):
        labels = container.get("Labels") or {}
        if labels.get("com.docker.compose.project") == PROJECT:
            continue
        details = docker_api("/containers/" + container["Id"] + "/json")
        host = details["HostConfig"]
        result[container["Id"]] = dict(
            names=container["Names"], image=details["Image"], started=details["State"]["StartedAt"],
            limits={key: host.get(key) for key in ("NanoCpus", "CpuQuota", "CpuPeriod", "CpusetCpus", "Memory")},
        )
    return result


def sample_one(identifier):
    raw = docker_api(f"/containers/{identifier}/stats?stream=false&one-shot=true")
    memory = raw.get("memory_stats", {})
    memory_detail = memory.get("stats", {})
    cpu = raw["cpu_stats"]
    if raw["read"].startswith("0001-"):
        raise RuntimeError(f"Container stopped while sampling: {identifier}")
    return dict(
        read_epoch=datetime.fromisoformat(raw["read"].replace("Z", "+00:00")).timestamp(),
        cpu_ns=cpu["cpu_usage"]["total_usage"], throttling=cpu.get("throttling_data", {}),
        memory_bytes=memory.get("usage", 0),
        working_set_bytes=max(0, memory.get("usage", 0)-memory_detail.get("inactive_file", memory_detail.get("total_inactive_file", 0))),
        pids=raw.get("pids_stats", {}).get("current"),
    )


def snapshot(containers):
    with ThreadPoolExecutor(max_workers=12) as pool:
        return dict(zip(containers, pool.map(sample_one, containers.values()), strict=True))


def sql_snapshot(connection):
    with connection.cursor() as cursor:
        cursor.execute("""SELECT coalesce(sum(calls),0), coalesce(sum(total_exec_time),0),
            coalesce(sum(shared_blks_hit),0), coalesce(sum(shared_blks_read),0),
            coalesce(sum(wal_bytes),0) FROM pg_stat_statements
            WHERE query NOT LIKE '%%pg_stat_%%'""")
        return dict(zip(("calls", "execution_ms", "buffer_hits", "buffer_reads", "wal_bytes"), map(float, cursor.fetchone()), strict=True))


def activity(connection):
    with connection.cursor() as cursor:
        cursor.execute("""SELECT application_name, state, wait_event_type, count(*)
            FROM pg_stat_activity WHERE datname=current_database()
            AND application_name IN ('matrix-web','matrix-telegram')
            GROUP BY application_name,state,wait_event_type""")
        return [dict(application=row[0], state=row[1], wait=row[2], count=row[3]) for row in cursor.fetchall()]


def summarize_resources(before, after):
    result = {}
    for name in before:
        a, b = before[name], after[name]
        elapsed = b["read_epoch"]-a["read_epoch"]
        cpu_seconds = (b["cpu_ns"]-a["cpu_ns"])/1e9
        result[name] = dict(cpu_seconds=cpu_seconds, elapsed_seconds=elapsed,
                            average_cpu_cores=cpu_seconds/elapsed,
                            throttled_seconds=(b["throttling"].get("throttled_time", 0)-a["throttling"].get("throttled_time", 0))/1e9,
                            throttled_periods=b["throttling"].get("throttled_periods", 0)-a["throttling"].get("throttled_periods", 0))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True, help="Git revision exported to the baseline snapshot")
    parser.add_argument("--current-ref", required=True, help="Git revision exported to the current snapshot")
    parser.add_argument("--runtime-image", default="ghcr.io/roxy-wi/incidentrelay:2.5")
    parser.add_argument("--postgres-image", default="postgres:16-alpine")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--include-telegram", action="store_true", help="Also measure the real unused Telegram worker")
    parser.add_argument("--only", choices=["baseline-on", "baseline-off", "current-on", "current-off"])
    args = parser.parse_args()
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    target = 65536 if hard == resource.RLIM_INFINITY else min(65536, hard)
    if target < 32768:
        raise RuntimeError(f"Host file-descriptor hard limit is too low: {hard}")
    resource.setrlimit(resource.RLIMIT_NOFILE, (max(soft, target), hard))
    lock = open("/tmp/incidentrelay-intake-bench.lock", "w")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    args.output.mkdir(parents=True, exist_ok=False)
    global SOCKET
    SOCKET = command("docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}").removeprefix("unix://")
    runtime_image = command("docker", "image", "inspect", args.runtime_image, "--format", "{{.Id}}")
    postgres_image = command("docker", "image", "inspect", args.postgres_image, "--format", "{{.Id}}")
    outside = inventory()
    vm_limits = {key: docker_api("/info")[key] for key in ("NCPU", "MemTotal")}
    metadata = dict(external_containers=outside, docker_info=docker_api("/info"),
                    runtime_image=runtime_image, postgres_image=postgres_image,
                    baseline=command("git", "rev-parse", args.baseline_ref), current=command("git", "rev-parse", args.current_ref),
                    seconds=args.seconds, rounds=args.rounds, host_load_generator=True,
                    host_load_generator_nofile=resource.getrlimit(resource.RLIMIT_NOFILE),
                    source_snapshots=str(args.root), harness_sha=command("shasum", "-a", "256", str(args.root/"harness/tools/benchmarks/capacity.py")))
    # Docker info contains host metadata; benchmark artifacts retain only useful fields.
    metadata["docker_info"] = {key: metadata["docker_info"].get(key) for key in ("NCPU", "MemTotal", "ServerVersion", "Architecture", "KernelVersion")}
    (args.output/"metadata.json").write_text(json.dumps(metadata, indent=2)+"\n")
    scenarios = ["baseline-off", "current-off"]
    if args.include_telegram:
        scenarios = ["baseline-on", "baseline-off", "current-on", "current-off"]
    if args.only:
        scenarios = [args.only]
    orders = [scenarios if number % 2 == 0 else list(reversed(scenarios)) for number in range(args.rounds)]
    for round_number, order in enumerate(orders, 1):
        for scenario in order:
            if inventory() != outside:
                raise RuntimeError("Outside container inventory/limits changed; comparison halted")
            if {key: docker_api("/info")[key] for key in vm_limits} != vm_limits:
                raise RuntimeError("Docker VM resource allocation changed; comparison halted")
            version, telegram = scenario.split("-")
            label = f"r{round_number}-{scenario}"
            output = args.output/label
            output.mkdir()
            env = dict(os.environ, SOURCE_DIR=str(args.root/version), HARNESS_DIR=str(args.root/"harness"),
                       RUNTIME_IMAGE=runtime_image, POSTGRES_IMAGE=postgres_image)
            native = dict(env, PYTHONPATH=str(args.root/version), PYTHONDONTWRITEBYTECODE="1",
                          INCIDENTRELAY_CONFIG_FILE=str(args.root/"harness/tools/benchmarks/benchmark.conf"),
                          INCIDENTRELAY__DATABASE__HOST="127.0.0.1", INCIDENTRELAY__DATABASE__PORT="55435",
                          BENCH_HTTP_HOST="127.0.0.1", BENCH_HTTP_PORT="18380", PGAPPNAME="matrix-validator",
                          BENCH_RUNS_FILE=str(output/"runs.jsonl"), BENCH_TIMELINE_DIR=str(output))
            client = [sys.executable, str(args.root/"harness/tools/benchmarks/capacity.py")]
            log = (output/"commands.txt").open("w")

            def compose(*arguments, env=env, log=log):
                subprocess.run(COMPOSE+list(arguments), env=env, stdout=log, stderr=subprocess.STDOUT, check=True)

            print(f"START {label}", flush=True)
            connection = None
            stop = threading.Event()
            monitor = server = None
            state = {"phase": "warmup"}
            snapshots = {}
            sample_errors = []
            try:
                compose("down")
                compose("up", "-d", "--wait", "postgres")
                subprocess.run(client+["setup"], cwd=args.root, env=native, stdout=log, stderr=subprocess.STDOUT, check=True)
                compose("up", "-d", "web", *(["telegram"] if telegram == "on" else []))
                containers = {item["Labels"]["com.docker.compose.service"]: item["Id"]
                              for item in docker_api("/containers/json")
                              if item.get("Labels", {}).get("com.docker.compose.project") == PROJECT}
                expected = {"web", "postgres", "telegram"} if telegram == "on" else {"web", "postgres"}
                if set(containers) != expected:
                    raise RuntimeError(f"Wrong benchmark container inventory: {containers}")
                time.sleep(5)
                subprocess.run(client+["run", "--async-client", "--seconds", "5", "--rate", "25", "--concurrency", "16384", "--request-timeout", "600", "--label", "warmup"],
                               cwd=args.root, env=native, stdout=log, stderr=subprocess.STDOUT, check=True)
                connection = psycopg2.connect(host="127.0.0.1", port=55435, dbname="ir_capacity_bench",
                                              user="ir_capacity_bench", password="benchmark-only", application_name="matrix-monitor")
                connection.autocommit = True
                all_containers = dict(containers, **{"outside:"+data["names"][0]: identifier for identifier, data in outside.items()})

                def collect(output=output, stop=stop, state=state, all_containers=all_containers, connection=connection, sample_errors=sample_errors):
                    with (output/"resources.jsonl").open("w") as stream:
                        while not stop.is_set():
                            try:
                                row = dict(epoch=time.time(), phase=state["phase"], containers=snapshot(all_containers),
                                           postgres_activity=activity(connection), host_load=os.getloadavg())
                                stream.write(json.dumps(row)+"\n")
                                stream.flush()
                            except Exception as error:
                                sample_errors.append(repr(error))
                                stream.write(json.dumps(dict(error=repr(error), epoch=time.time()))+"\n")
                                stream.flush()
                                stop.set()
                            stop.wait(1)

                class BoundaryHandler(BaseHTTPRequestHandler):
                    def log_message(self, *args):
                        pass

                    def do_GET(self, snapshots=snapshots, containers=containers):
                        snapshots[self.path] = snapshot(containers)
                        self.send_response(200)
                        self.end_headers()
                        self.wfile.write(b"ok")

                server = ThreadingHTTPServer(("127.0.0.1", 0), BoundaryHandler)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                native["BENCH_METRICS_URL"] = f"http://127.0.0.1:{server.server_port}"
                monitor = threading.Thread(target=collect)
                monitor.start()
                state["phase"] = "idle"
                idle_before = snapshot(containers)
                sql_before = sql_snapshot(connection)
                time.sleep(8)
                idle_after = snapshot(containers)
                sql_after = sql_snapshot(connection)
                (output/"idle.json").write_text(json.dumps(dict(resources=summarize_resources(idle_before, idle_after),
                            sql_delta={key: sql_after[key]-sql_before[key] for key in sql_before}), indent=2)+"\n")
                for phase, rate, concurrency in (("steady", 100, 16384), ("overload", 400, 16384), ("saturation", 0, 128)):
                    if inventory() != outside:
                        raise RuntimeError("Outside container inventory/limits changed during case")
                    state["phase"] = phase
                    sql_before = sql_snapshot(connection)
                    snapshots.clear()
                    completed = subprocess.run(client+["run", "--async-client", "--seconds", str(args.seconds), "--rate", str(rate),
                                               "--concurrency", str(concurrency), "--request-timeout", "600", "--label", phase],
                                               cwd=args.root, env=native, capture_output=True, text=True, check=True)
                    (output/f"{phase}-output.txt").write_text(completed.stdout+completed.stderr)
                    row = next(json.loads(line) for line in completed.stdout.splitlines() if line.startswith("{"))
                    if sample_errors:
                        raise RuntimeError(f"Resource collection failed: {sample_errors}")
                    for key in ("persisted_unique_alerts", "persisted_unique_groups", "persisted_completed_full_traces", "traces_with_steps"):
                        if row[key] != row["success"]:
                            raise RuntimeError(f"Persistence mismatch: {key} {row}")
                    if row["errors"] or row["client_rejected"]:
                        raise RuntimeError(f"Client/HTTP failures invalidate capacity measurement: {row}")
                    sql_after = sql_snapshot(connection)
                    row.update(scenario=scenario, round=round_number, resources=summarize_resources(snapshots["/start"], snapshots["/end"]),
                               sql_delta={key: sql_after[key]-sql_before[key] for key in sql_before})
                    own_cpu = sum(value["cpu_seconds"] for value in row["resources"].values())
                    row["stack_cpu_ms_per_event"] = own_cpu*1000/row["success"]
                    (output/f"{phase}.json").write_text(json.dumps(row, indent=2)+"\n")
                    with (args.output/"summary.jsonl").open("a") as stream:
                        stream.write(json.dumps(row)+"\n")
                    print(f"DONE {label} {phase}: {row['success_per_second']}/s; backlog={row['backlog_at_offer_end']}; drain={row['drain_seconds']}s", flush=True)
                    time.sleep(2)
                if inventory() != outside:
                    raise RuntimeError("Outside container inventory changed; case invalid")
                (output/"valid.json").write_text(json.dumps(dict(external_inventory_unchanged=True))+"\n")
            finally:
                stop.set()
                if monitor:
                    monitor.join(timeout=30)
                    if monitor.is_alive():
                        raise RuntimeError("Resource sampler did not stop cleanly")
                if server:
                    server.shutdown()
                    server.server_close()
                if connection:
                    connection.close()
                try:
                    compose("logs", "--no-color", "--tail", "100")
                finally:
                    compose("down")
                log.close()


if __name__ == "__main__":
    main()
