"""Visualize load-test latencies and report p95.

Usage:
    uv run python scripts/visualize_latency.py results/latency_<run>.csv

The chart is written next to the CSV with a matching name and .png extension.
"""

import argparse
import csv
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot request latency and report p95."
    )
    parser.add_argument(
        "csv_path",
        type=Path,
        help="Load-test CSV produced by scripts/load_test.py",
    )
    args = parser.parse_args()

    started, latencies = load_latencies(args.csv_path)
    if not latencies:
        raise SystemExit(f"No successful requests found in {args.csv_path}")

    sorted_latencies = sorted(latencies)
    p50 = percentile(sorted_latencies, 0.50)
    p95 = percentile(sorted_latencies, 0.95)
    p99 = percentile(sorted_latencies, 0.99)

    figure, (timeline, histogram) = plt.subplots(
        2,
        1,
        figsize=(12, 8),
        constrained_layout=True,
    )
    figure.suptitle(
        f"Offers latency - {len(latencies)} requests, p95 = {p95:.1f} ms"
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
    histogram.set_xlabel("Latency (ms)")
    histogram.set_ylabel("Requests")
    histogram.set_title("Latency distribution")
    histogram.grid(alpha=0.3)
    histogram.legend()

    output = args.csv_path.with_suffix(".png")
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=150)

    print(f"Requests: {len(latencies)}")
    print(
        f"p50={p50:.1f} ms, p95={p95:.1f} ms, p99={p99:.1f} ms, "
        f"max={sorted_latencies[-1]:.1f} ms"
    )
    print(f"Chart written to {output}")


if __name__ == "__main__":
    main()
