"""Generate latency charts for every CSV in the results directory.

Usage:
    uv run python scripts/visualize_latency.py

Each results/<name>.csv gets a matching results/<name>.png chart.
"""

import csv
import math
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "results"


def percentile(sorted_values: list[float], fraction: float) -> float:
    """Return the linearly interpolated percentile of sorted values."""
    if not sorted_values:
        return 0.0
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return (
        sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight
    )


def request_rate_from_filename(path: Path) -> float | None:
    match = re.search(r"_(\d+(?:\.\d+)?)rps(?:_\d+)?\.csv$", path.name)
    return float(match.group(1)) if match else None


def load_latencies(path: Path) -> tuple[list[float], list[float]]:
    with path.open(newline="") as file:
        rows = [
            row
            for row in csv.DictReader(file)
            if row["status_code"] == "200"
        ]

    started = [float(row["started_s"]) for row in rows]
    latencies = [float(row["latency_ms"]) for row in rows]
    return started, latencies


def create_chart(csv_path: Path) -> tuple[int, float, float, Path] | None:
    started, latencies = load_latencies(csv_path)
    if not latencies:
        print(f"Skipping {csv_path.name}: no successful requests")
        return None

    sorted_latencies = sorted(latencies)
    p50 = percentile(sorted_latencies, 0.50)
    p95 = percentile(sorted_latencies, 0.95)
    p99 = percentile(sorted_latencies, 0.99)
    request_rate = request_rate_from_filename(csv_path)
    rate_label = (
        f"target {request_rate:g} req/s"
        if request_rate is not None
        else "unknown target rate"
    )

    figure, (timeline, histogram) = plt.subplots(
        2,
        1,
        figsize=(12, 8),
        constrained_layout=True,
    )
    figure.suptitle(
        f"Offers latency - {rate_label}\n"
        f"{len(latencies)} requests, "
        f"p95 = {p95:.1f} ms, p99 = {p99:.1f} ms"
    )

    timeline.plot(
        started,
        latencies,
        marker=".",
        linestyle="none",
        alpha=0.6,
        label="requests",
    )
    timeline.axhline(
        p50,
        color="orange",
        linestyle=":",
        linewidth=1.5,
        label=f"p50 = {p50:.1f} ms",
    )
    timeline.axhline(
        p95,
        color="red",
        linestyle="--",
        linewidth=1.5,
        label=f"p95 = {p95:.1f} ms",
    )
    timeline.axhline(
        p99,
        color="purple",
        linestyle="-.",
        linewidth=1.5,
        label=f"p99 = {p99:.1f} ms",
    )
    timeline.set_xlabel("Elapsed time (s)")
    timeline.set_ylabel("Latency (ms)")
    timeline.set_title("Latency over time")
    timeline.grid(alpha=0.3)
    timeline.legend()

    bins = min(50, max(10, int(len(latencies) ** 0.5) * 2))
    histogram.hist(
        latencies,
        bins=bins,
        edgecolor="black",
        alpha=0.7,
    )
    histogram.axvline(
        p50,
        color="orange",
        linestyle=":",
        linewidth=1.5,
        label=f"p50 = {p50:.1f} ms",
    )
    histogram.axvline(
        p95,
        color="red",
        linestyle="--",
        linewidth=1.5,
        label=f"p95 = {p95:.1f} ms",
    )
    histogram.axvline(
        p99,
        color="purple",
        linestyle="-.",
        linewidth=1.5,
        label=f"p99 = {p99:.1f} ms",
    )
    histogram.set_xlabel("Latency (ms)")
    histogram.set_ylabel("Requests")
    histogram.set_title("Latency distribution")
    histogram.grid(alpha=0.3)
    histogram.legend()

    output = csv_path.with_suffix(".png")
    figure.savefig(output, dpi=150)
    plt.close(figure)

    return len(latencies), request_rate, p95, p99, output


def main() -> None:
    csv_paths = sorted(RESULTS_DIR.glob("*.csv"))
    if not csv_paths:
        raise SystemExit(f"No CSV files found in {RESULTS_DIR}")

    for index, csv_path in enumerate(csv_paths, start=1):
        try:
            result = create_chart(csv_path)
        except (KeyError, ValueError) as error:
            print(f"Skipping {csv_path.name}: {error}")
            continue

        if result is None:
            continue

        requests, request_rate, p95, p99, output = result
        rate_text = (
            f"{request_rate:g} req/s"
            if request_rate is not None
            else "unknown rate"
        )
        print(
            f"[{index}/{len(csv_paths)}] {csv_path.name}: "
            f"{requests} requests, target={rate_text}, "
            f"p95={p95:.1f} ms, p99={p99:.1f} ms -> {output.name}"
        )


if __name__ == "__main__":
    main()
