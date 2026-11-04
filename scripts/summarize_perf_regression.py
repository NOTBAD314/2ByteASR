"""Compare perf_regression_audit runs side by side.

Usage: python scripts/summarize_perf_regression.py label=tmp/run1 label2=tmp/run2 ...
Distributions are p50/p95/max over every sample (never only the best one).
"""
import json
import statistics
import sys
from pathlib import Path


def dist(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return "-"
    pick = lambda q: values[min(len(values) - 1, int(round((len(values) - 1) * q)))]
    return f"{pick(.5):.0f}/{pick(.95):.0f}/{values[-1]:.0f}"


def load(path):
    path = Path(path)
    return json.loads((path / "perf.json" if path.is_dir() else path).read_text("utf8"))


def main():
    runs = [(arg.split("=", 1)[0], load(arg.split("=", 1)[1])) for arg in sys.argv[1:]]
    width = 26
    print("metric (p50/p95/max ms)".ljust(40) + "".join(label.rjust(width) for label, _ in runs))

    def row(name, values):
        print(name.ljust(40) + "".join(str(v).rjust(width) for v in values))
    row("build", [str((d.get("build") or {}).get("build_channel", d.get("runner_exe", "?")))[:24] for _, d in runs])
    row("cues / speakers", [f"{d.get('cue_count')}/{d.get('speakers')}" for _, d in runs])
    row("open ready s", [d.get("open_ready_s") for _, d in runs])
    actions = []
    for _, d in runs:
        for name in d.get("actions", {}):
            if name not in actions:
                actions.append(name)
    for name in actions:
        for metric in ("handler_ms", "frame_ms", "idle_ms"):
            row(f"{name} {metric}", [dist(d.get("actions", {}).get(name, {}).get(metric, [])) for _, d in runs])
    gestures = []
    for _, d in runs:
        for name in d.get("gestures", {}):
            if name not in gestures:
                gestures.append(name)
    for name in gestures:
        for metric in ("press_handler_ms", "press_frame_ms", "first_move_frame_ms", "stall_after_release_ms"):
            row(f"{name} {metric}", [dist([g.get(metric) for g in d.get("gestures", {}).get(name, [])]) for _, d in runs])
        for metric in ("move_frame_ms", "frame_interval_ms"):
            row(f"{name} {metric} p95 by repeat", [
                ",".join(str(g.get(metric, {}).get("p95", "-")) for g in d.get("gestures", {}).get(name, []))
                for _, d in runs])
    phases = []
    for _, d in runs:
        for name in d.get("loop", {}):
            if name not in phases:
                phases.append(name)
    for name in phases:
        row(f"[{name}] stalls >=100/250", [
            f"{d['loop'].get(name, {}).get('stalls_100ms', '-')}/{d['loop'].get(name, {}).get('stalls_250ms', '-')}"
            for _, d in runs])
        row(f"[{name}] cpu_s / wall_s", [
            f"{d.get('phases', {}).get(name, {}).get('cpu_s', '-')}/{d.get('phases', {}).get(name, {}).get('seconds', '-')}"
            for _, d in runs])
    for label in ("idle:before", "closed-0", "closed-2", "reopened-2", "idle-final:after"):
        row(f"rss/handles {label}", [
            next((f"{r.get('rss_mb')}/{r.get('handles')}" for r in d.get("resources", []) if r.get("label") == label), "-")
            for _, d in runs])
    row("reopen / cycle ready s", [f"{d.get('reopen_ready_s')}/{d.get('cycle_ready_s')}" for _, d in runs])
    row("errors", [",".join(d.get("errors", {})) or "-" for _, d in runs])
    for label, d in runs:
        print(label, "checks:", json.dumps(d.get("checks"), ensure_ascii=False))


if __name__ == "__main__":
    main()
