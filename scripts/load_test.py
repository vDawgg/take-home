"""Send rate-limited requests to the offers endpoint and record latencies.

Usage:
    uv run python scripts/load_test.py --rate 100

Writes one CSV row per request to a timestamped file under results/.
"""

import argparse
import asyncio
import csv
import math
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "results"
DEFAULT_MAX_USER_ID = 20_000


@dataclass
class Result:
    request_index: int
    user_id: int
    status_code: int
    latency_ms: float
    started_s: float
    finished_s: float


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


async def send_request(
    client: httpx.AsyncClient,
    url: str,
    request_index: int,
    user_id: int,
    test_start: float,
) -> Result:
    started = time.perf_counter()
    try:
        response = await client.get(url, params={"user_id": user_id})
        status_code = response.status_code
    except httpx.HTTPError:
        status_code = 0
    finished = time.perf_counter()

    return Result(
        request_index=request_index,
        user_id=user_id,
        status_code=status_code,
        latency_ms=(finished - started) * 1000,
        started_s=started - test_start,
        finished_s=finished - test_start,
    )


async def run_load_test(args: argparse.Namespace) -> list[Result]:
    rng = random.Random(args.seed)
    user_ids = [
        rng.randint(1, args.max_user_id) for _ in range(args.requests)
    ]
    interval = 1.0 / args.rate
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%d-%m-%Y_%H-%M")
    name = f"latency_{timestamp}_{args.requests}req_{args.rate:g}rps"
    output = RESULTS_DIR / f"{name}.csv"
    suffix = 2
    while output.exists():
        output = RESULTS_DIR / f"{name}_{suffix}.csv"
        suffix += 1

    # Override httpx's default 100-connection cap so the request rate is the
    # only thing controlling load; concurrency follows from rate and latency.
    limits = httpx.Limits()

    async with httpx.AsyncClient(
        limits=limits,
        timeout=args.timeout,
    ) as client:
        test_start = time.perf_counter()
        tasks: list[asyncio.Task[Result]] = []

        for request_index, user_id in enumerate(user_ids):
            target = test_start + request_index * interval
            delay = target - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)

            tasks.append(
                asyncio.create_task(
                    send_request(
                        client,
                        args.url,
                        request_index,
                        user_id,
                        test_start,
                    )
                )
            )

        results = await asyncio.gather(*tasks)
        wall_time = time.perf_counter() - test_start

    results.sort(key=lambda result: result.request_index)
    write_results(results, output)

    successful = [
        result for result in results if 200 <= result.status_code < 300
    ]
    latencies = sorted(result.latency_ms for result in successful)
    failed = len(results) - len(successful)

    print(
        f"Sent {len(results)} requests at {args.rate:g} req/s "
        f"in {wall_time:.2f}s ({len(results) / wall_time:.1f} req/s effective)"
    )
    print(f"Successful: {len(successful)}, failed: {failed}")

    if latencies:
        p95 = percentile(latencies, 0.95)
        print(
            "Latency (ms): "
            f"min={latencies[0]:.1f}, "
            f"mean={sum(latencies) / len(latencies):.1f}, "
            f"p50={percentile(latencies, 0.50):.1f}, "
            f"p95={p95:.1f}, "
            f"p99={percentile(latencies, 0.99):.1f}, "
            f"max={latencies[-1]:.1f}"
        )

    print(f"Results written to {output}")
    return results


def write_results(results: list[Result], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "request_index",
                "user_id",
                "status_code",
                "latency_ms",
                "started_s",
                "finished_s",
            ]
        )
        for result in results:
            writer.writerow(
                [
                    result.request_index,
                    result.user_id,
                    result.status_code,
                    f"{result.latency_ms:.3f}",
                    f"{result.started_s:.6f}",
                    f"{result.finished_s:.6f}",
                ]
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send rate-limited requests to GET /offers and record latency."
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000/offers",
        help="Offers endpoint URL",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=1000,
        help="Number of requests to send (default: 1000)",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=100.0,
        help="Target request rate in requests per second (default: 100)",
    )
    parser.add_argument(
        "--max-user-id",
        type=int,
        default=DEFAULT_MAX_USER_ID,
        help=f"Maximum seeded user ID (default: {DEFAULT_MAX_USER_ID})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for repeatable user IDs (default: 42)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Per-request timeout in seconds (default: 30)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(run_load_test(parse_args()))
