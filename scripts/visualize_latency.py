"""Generate latency charts for every CSV in the results directory.

Usage:
    uv run python scripts/visualize_latency.py

Each results/<name>.csv gets a matching results/<name>.pdf chart.
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


def metadata_from_filename(
    path: Path,
) -> tuple[float | None, int | None]:
    match = re.search(
        r"_(\d+(?:\.\d+)?)rps(?:_(\d+)users)?(?:_\d+)?\.csv$",
        path.name,
    )
    if not match:
        return None, None
    request_rate = float(match.group(1))
    user_count = int(match.group(2)) if match.group(2) else None
    return request_rate, user_count


def load_latencies(
    path: Path,
) -> tuple[list[float], list[float], int, int]:
    with path.open(newline="") as file:
        rows = [
            row
            for row in csv.DictReader(file)
            if row["status_code"] == "200"
        ]

    started = [float(row["started_s"]) for row in rows]
    latencies = [float(row["latency_ms"]) for row in rows]
    cache_hits = sum(
        1 for row in rows if row.get("cache_status") == "HIT"
    )
    cache_misses = sum(
        1 for row in rows if row.get("cache_status") == "MISS"
    )
    return started, latencies, cache_hits, cache_misses


def create_chart(
    csv_path: Path,
) -> tuple[int, float, int | None, float, float, float, int, int, Path] | None:
    started, latencies, cache_hits, cache_misses = load_latencies(csv_path)
    if not latencies:
        print(f"Skipping {csv_path.name}: no successful requests")
        return None

    sorted_latencies = sorted(latencies)
    average = sum(latencies) / len(latencies)
    p50 = percentile(sorted_latencies, 0.50)
    p95 = percentile(sorted_latencies, 0.95)
    p99 = percentile(sorted_latencies, 0.99)
    request_rate, user_count = metadata_from_filename(csv_path)
    if request_rate is None:
        rate_label = "unknown target rate"
    elif user_count is None:
        rate_label = f"target {request_rate:g} req/s"
    else:
        rate_label = (
            f"target {request_rate:g} req/s, {user_count} users"
        )

    figure, (timeline, histogram) = plt.subplots(
        2,
        1,
        figsize=(12, 8),
        constrained_layout=True,
    )
    cache_total = cache_hits + cache_misses
    cache_label = ""
    if cache_total:
        hit_rate = cache_hits / cache_total * 100
        cache_label = (
            f"\nDB calls: {cache_misses}, cache hit rate: {hit_rate:.1f}%"
        )

    figure.suptitle(
        f"Offers latency - {rate_label}\n"
        f"{len(latencies)} requests, avg = {average:.1f} ms, "
        f"p95 = {p95:.1f} ms, p99 = {p99:.1f} ms"
        f"{cache_label}"
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
        average,
        color="green",
        linestyle="--",
        linewidth=1.5,
        label=f"avg = {average:.1f} ms",
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
        average,
        color="green",
        linestyle="--",
        linewidth=1.5,
        label=f"avg = {average:.1f} ms",
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

    output = csv_path.with_suffix(".pdf")
    figure.savefig(output, dpi=150)
    plt.close(figure)

    return (
        len(latencies),
        request_rate,
        user_count,
        average,
        p95,
        p99,
        cache_hits,
        cache_misses,
        output,
    )


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

        (
            requests,
            request_rate,
            user_count,
            average,
            p95,
            p99,
            cache_hits,
            cache_misses,
            output,
        ) = result
        rate_text = (
            f"{request_rate:g} req/s"
            if request_rate is not None
            else "unknown rate"
        )
        users_text = (
            f", users={user_count}" if user_count is not None else ""
        )
        cache_text = ""
        if cache_hits + cache_misses:
            hit_rate = cache_hits / (cache_hits + cache_misses) * 100
            cache_text = (
                f", db_calls={cache_misses}, hit_rate={hit_rate:.1f}%"
            )
        print(
            f"[{index}/{len(csv_paths)}] {csv_path.name}: "
            f"{requests} requests, target={rate_text}{users_text}, "
            f"avg={average:.1f} ms, p95={p95:.1f} ms, "
            f"p99={p99:.1f} ms{cache_text} -> {output.name}"
        )


if __name__ == "__main__":
    main()
