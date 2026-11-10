"""Render alert-intake throughput, latency, backlog, and resource comparisons."""
import argparse
import gzip
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


VERSIONS = ("baseline", "current")
COLORS = ("#4a76a8", "#398b62")
COMPONENTS = {"web": "#4a76a8", "postgres": "#438d86"}


def read_samples(root, name):
    path = root/f"{name}-resources.jsonl.gz"
    if not path.exists():
        path = root/"resources.jsonl.gz"
    if path.exists():
        with gzip.open(path, "rt") as stream:
            return [json.loads(line) for line in stream]
    return [json.loads(line) for line in (root/"resources.jsonl").read_text().splitlines()]


def load_measurements(root):
    saved = root/"measurements.json"
    if saved.exists():
        return json.loads(saved.read_text())["runs"], {name: root for name in VERSIONS}
    rows, samples_at = [], {}
    for name in VERSIONS:
        directory = root/f"r1-{name}-off"
        if not (directory/"valid.json").exists():
            raise RuntimeError(f"Case did not pass validation: {directory}")
        samples_at[name] = directory
        samples = read_samples(directory, name)
        for phase in ("steady", "overload", "saturation"):
            row = json.loads((directory/f"{phase}.json").read_text())
            window = [sample for sample in samples if row["started_epoch"] <= sample["epoch"] <= row["ended_epoch"]]
            peak = max(window, key=lambda sample: sum(sample["containers"][key]["working_set_bytes"] for key in COMPONENTS))
            row["peak_working_set_mib"] = {key: peak["containers"][key]["working_set_bytes"]/2**20 for key in COMPONENTS}
            row["peak_stack_mib"] = sum(row["peak_working_set_mib"].values())
            row.update(scenario=name, phase=phase, timeline=json.loads((directory/f"{phase}-timeline.json").read_text()))
            rows.append(row)
    return rows, samples_at


def render(root):
    rows, samples_at = load_measurements(root)
    metadata_path = root/"metadata.json"
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    baseline = metadata.get("baseline", "baseline")
    current = metadata.get("current", "current")
    for row in rows:
        expected = row["success"]
        for key in ("offered", "completed", "persisted_unique_alerts", "persisted_unique_groups", "persisted_completed_full_traces", "traces_with_steps"):
            if row[key] != expected:
                raise RuntimeError(f"Persistence/completion mismatch: {key}")
        if row["errors"] or row["client_rejected"] or row["timeline"][-1]["outstanding"]:
            raise RuntimeError("Probe has failures, admission rejections or undrained requests")

    def records(phase):
        return [next(row for row in rows if row["scenario"] == name and row["phase"] == phase) for name in VERSIONS]

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.titleweight": "bold", "figure.facecolor": "white"})

    def bars(ax, values, title, ylabel):
        ax.bar(range(2), values, width=.6, color=COLORS)
        for index, value in enumerate(values):
            ax.annotate(f"{value:,.1f}", (index, value), xytext=(0, 7), textcoords="offset points", ha="center")
        ax.set_xticks(range(2), ("Baseline", "Current"))
        ax.set_title(title, loc="left", pad=15)
        ax.set_ylabel(ylabel)
        ax.set_ylim(0, max(values)*1.3)
        ax.grid(axis="y", alpha=.15)
        ax.set_axisbelow(True)

    overload_count = records("overload")[0]["offered"]
    offer_seconds = records("steady")[0]["seconds"]
    events_before_saturation = 125 + records("steady")[0]["offered"] + overload_count
    saturation_clients = records("saturation")[0]["concurrency"]
    vm_cpus = metadata.get("docker_info", {}).get("NCPU")
    vm_label = f"{vm_cpus}-CPU VM" if vm_cpus else "Docker VM"
    fig, axes = plt.subplots(2, 3, figsize=(17, 10))
    bars(axes[0, 0], [row["success_per_second"] for row in records("saturation")], "Completed throughput · saturation", "Completed requests/sec, including drain")
    for ax, phase, field, title, ylabel in (
        (axes[0, 1], "saturation", "cpu", "CPU cost · saturation", "CPU ms per completed request"),
        (axes[0, 2], "overload", "memory", f"Peak memory · same {overload_count:,}-request workload", "MiB, stack working set"),
    ):
        bottom = np.zeros(2)
        for component, color in COMPONENTS.items():
            values = [row["resources"][component]["cpu_seconds"]*1000/row["success"] if field == "cpu"
                      else row["peak_working_set_mib"][component] for row in records(phase)]
            ax.bar(range(2), values, bottom=bottom, width=.6, color=color, label=component.capitalize())
            bottom += values
        for index, total in enumerate(bottom):
            ax.annotate(f"{total:,.1f}", (index, total), xytext=(0, 7), textcoords="offset points", ha="center")
        ax.set_xticks(range(2), ("Baseline", "Current"))
        ax.set_title(title, loc="left", pad=15)
        ax.set_ylabel(ylabel)
        ax.set_ylim(0, max(bottom)*1.25)
        ax.legend(frameon=False, ncol=2, loc="upper left")
        ax.grid(axis="y", alpha=.15)
        ax.set_axisbelow(True)
    seconds = records("overload")[0]["seconds"]
    for index, row in enumerate(records("overload")):
        timeline = row["timeline"]
        axes[1, 0].plot([0]+[entry["seconds"] for entry in timeline], [0]+[entry["outstanding"] for entry in timeline], color=COLORS[index], label=row["scenario"].capitalize())
    axes[1, 0].axvline(seconds, color="#444444", linestyle=":", label="Arrivals stop")
    axes[1, 0].set(title="Backpressure + drain · 400 offered/sec", xlabel="Seconds from first arrival", ylabel="Uncompleted scheduled requests")
    axes[1, 0].legend(frameon=False)
    axes[1, 0].grid(alpha=.15)
    bars(axes[1, 1], [row["drain_seconds"] for row in records("overload")], "Time to drain after arrivals stop", "Seconds")
    bars(axes[1, 2], [row["http_p95_ms"] for row in records("steady")], "p95 HTTP latency · 100 offered/sec", "Milliseconds")
    fig.suptitle("Alert processing: baseline vs current", fontsize=19, x=.06, ha="left", y=.985)
    fig.text(.06, .935, "Telegram disabled · identical images and CPU limits · fresh PostgreSQL · full traces verified", fontsize=11, color="#43505b")
    fig.text(.06, .02, f"Web ≤3 CPUs · PostgreSQL ≤2 · {vm_label} · host load generator · memory includes tmpfs database.", fontsize=10, color="#43505b")
    fig.subplots_adjust(top=.86, bottom=.14, hspace=.48, wspace=.3)
    fig.savefig(root/"comparison.png", dpi=160)
    plt.close(fig)

    resource_logs_available = all(
        any((samples_at[name]/filename).exists() for filename in
            (f"{name}-resources.jsonl.gz", "resources.jsonl.gz", "resources.jsonl"))
        for name in VERSIONS
    )
    if resource_logs_available:
        fig, axes = plt.subplots(2, 2, figsize=(15, 7), sharex=True)
        memory_ceiling = max(max(row["peak_working_set_mib"].values()) for row in records("overload"))
        for index, row in enumerate(records("overload")):
            samples = [sample for sample in read_samples(samples_at[row["scenario"]], row["scenario"]) if row["started_epoch"] <= sample["epoch"] <= row["ended_epoch"]]
            for component, color in COMPONENTS.items():
                times, cores = [], []
                for a, b in zip(samples, samples[1:], strict=False):
                    start, end = a["containers"][component], b["containers"][component]
                    times.append(end["read_epoch"]-row["started_epoch"])
                    cores.append((end["cpu_ns"]-start["cpu_ns"])/1e9/(end["read_epoch"]-start["read_epoch"]))
                axes[index, 0].plot(times, cores, color=color, label=component.capitalize())
                axes[index, 1].plot([sample["epoch"]-row["started_epoch"] for sample in samples], [sample["containers"][component]["working_set_bytes"]/2**20 for sample in samples], color=color)
            for ax in axes[index]:
                ax.axvline(seconds, color="#444444", linestyle=":")
                ax.grid(alpha=.15)
            axes[index, 0].set(title=row["scenario"].capitalize(), ylabel="CPU cores", ylim=(0, 3.1))
            axes[index, 1].set(ylabel="Working-set MiB", ylim=(0, np.ceil(memory_ceiling/100)*100))
        axes[0, 0].legend(frameon=False, ncol=2, loc="upper left")
        axes[-1, 0].set_xlabel("Seconds; dotted line = arrivals stop")
        axes[-1, 1].set_xlabel("Seconds")
        fig.suptitle("Resource utilization during overload and drain", fontsize=18)
        fig.tight_layout(rect=(0, .01, 1, .96), h_pad=2)
        fig.savefig(root/"resources.png", dpi=150)
        plt.close(fig)

    else:
        print("Resource timeline rendering skipped: raw benchmark resource logs are not available.")

    input_description = "Measurements and request timelines are in measurements.json. Resource timeline charts require the resource logs generated by a benchmark run." if (root/"measurements.json").exists() else "Raw measurements, request timelines, and resource samples are in the benchmark run directories."
    if (root/"validation.json").exists():
        input_description += " Validation results are in validation.json."
    lines = ["# Alert-processing benchmark", "", "Baseline and current application.", "", "_Note: telegram container was disabled in both runs._", "",
             "![Comparison](comparison.png)", "", "![CPU and memory timelines](resources.png)", "",
             "| Measurement | Baseline | Current |", "|---|---:|---:|"]
    for phase, key, label in (("saturation", "success_per_second", "Completed requests/sec"),
                             ("saturation", "stack_cpu_ms_per_event", "CPU ms/completed request"),
                             ("overload", "peak_stack_mib", "Peak working-set MiB"),
                             ("steady", "http_p95_ms", "p95 latency at 100/sec (ms)"),
                             ("overload", "backlog_at_offer_end", "Backlog after overload offer"),
                             ("overload", "drain_seconds", "Drain time (seconds)"),
                             ("overload", "drain_success_per_second", "Successful completions/sec during drain")):
        values = [row[key] for row in records(phase)]
        lines.append(f"| {label} | {values[0]:,.2f} | {values[1]:,.2f} |")
    lines += ["", "## Method", "",
              f"Compared `{baseline}` with `{current}` using the same runtime images, four Gunicorn workers with four threads each, and a fresh PostgreSQL database. Limits: web three CPUs and PostgreSQL two CPUs. The load generator runs on the host.",
              f"Each run receives 125 warmup events, then {offer_seconds:g}-second probes at 100/sec, 400/sec, and {saturation_clients}-client saturation. Saturation starts after {events_before_saturation:,} completed events. The overload offer contains {overload_count:,} unique requests.",
              "Every successful response is matched to persisted alerts, distinct groups, completed full traces and trace steps. CPU includes app and PostgreSQL. Memory is working-set usage and includes tmpfs database storage; memory is compared at the same request count.", "",
              input_description, ""]
    (root/"REPORT.md").write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    render(args.directory)


if __name__ == "__main__":
    main()
