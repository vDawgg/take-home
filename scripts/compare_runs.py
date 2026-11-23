"""Compare base, index, and read-model runs across request rates.

Usage:
    uv run python scripts/compare_runs.py
    uv run python scripts/compare_runs.py --metric avg
"""

import argparse
import csv
import math
import re
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LogNorm

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "results"

RUN_PATTERNS = (
    ("base", re.compile(r"^base_latency_")),
    ("index", re.compile(r"^index_latency_")),
    ("read", re.compile(r"^read_model_latency_")),
)
RATE_PATTERN = re.compile(r"_(\d+(?:\.\d+)?)rps(?:_.*)?\.csv$")


def percentile(sorted_values: list[float], fraction: float) -> float:
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


def metric_value(latencies: list[float], metric: str) -> float:
    sorted_latencies = sorted(latencies)
    if metric == "avg":
        return sum(sorted_latencies) / len(sorted_latencies)
    if metric == "p95":
        return percentile(sorted_latencies, 0.95)
    return percentile(sorted_latencies, 0.99)


def load_run_latencies(path: Path) -> list[float]:
    with path.open(newline="") as file:
        return [
            float(row["latency_ms"])
            for row in csv.DictReader(file)
            if row["status_code"] == "200"
        ]


def collect_results() -> dict[tuple[str, float], list[float]]:
    grouped: dict[tuple[str, float], list[float]] = defaultdict(list)

    for path in sorted(RESULTS_DIR.glob("*.csv")):
        run_name = next(
            (name for name, pattern in RUN_PATTERNS if pattern.search(path.name)),
            None,
        )
        if run_name is None:
            continue

        rate_match = RATE_PATTERN.search(path.name)
        if rate_match is None:
            continue

        rate = float(rate_match.group(1))
        latencies = load_run_latencies(path)
        if latencies:
            grouped[(run_name, rate)].extend(latencies)

    return grouped


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Heatmap of base/index/read latency by request rate."
    )
    parser.add_argument(
        "--metric",
        choices=("avg", "p95", "p99"),
        default="p99",
        help="Latency metric to plot (default: p99)",
    )
    args = parser.parse_args()

    grouped = collect_results()
    if not grouped:
        raise SystemExit(f"No base/index/read result CSVs found in {RESULTS_DIR}")

    run_names = [name for name, _ in RUN_PATTERNS]
    rates = sorted({rate for _, rate in grouped})
    values = np.full((len(run_names), len(rates)), np.nan)

    for row, run_name in enumerate(run_names):
        for column, rate in enumerate(rates):
            latencies = grouped.get((run_name, rate))
            if latencies:
                values[row, column] = metric_value(latencies, args.metric)

    metric_label = {
        "avg": "average",
        "p95": "p95",
        "p99": "p99",
    }[args.metric]

    figure, axis = plt.subplots(
        figsize=(9, 4.5),
        constrained_layout=True,
    )
    masked_values = np.ma.masked_invalid(values)
    image = axis.imshow(
        masked_values,
        aspect="auto",
        cmap="RdYlGn_r",
        norm=LogNorm(
            vmin=max(0.1, float(np.nanmin(values))),
            vmax=float(np.nanmax(values)),
        ),
    )

    for row, run_name in enumerate(run_names):
        for column, rate in enumerate(rates):
            value = values[row, column]
            if np.isnan(value):
                text = "n/a"
                color = "black"
            else:
                text = f"{value:.1f}"
                color = "white" if image.norm(value) > 0.6 else "black"
            axis.text(
                column,
                row,
                text,
                ha="center",
                va="center",
                fontsize=10,
                color=color,
            )

    axis.set_xticks(range(len(rates)), [f"{rate:g}" for rate in rates])
    axis.set_yticks(range(len(run_names)), run_names)
    axis.set_xlabel("Target request rate (req/s)")
    axis.set_ylabel("Implementation")
    axis.set_title(
        f"Offers latency comparison - {metric_label} "
        "(ms, lower is better, log color scale)"
    )

    colorbar = figure.colorbar(image, ax=axis)
    colorbar.set_label(f"{metric_label} latency (ms, log scale)")

    output = RESULTS_DIR / f"comparison_{args.metric}.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=150)
    plt.close(figure)

    header = "run".ljust(8) + "".join(f"{rate:>10g}" for rate in rates)
    print(header)
    for row, run_name in enumerate(run_names):
        cells = "".join(
            (
                f"{values[row, column]:>10.1f}"
                if not np.isnan(values[row, column])
                else f"{'n/a':>10}"
            )
            for column in range(len(rates))
        )
        print(run_name.ljust(8) + cells)

    print(f"\nHeatmap written to {output}")


if __name__ == "__main__":
    main()
