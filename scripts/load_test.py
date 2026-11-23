"""Send rate-limited requests to the offers endpoint and record latencies.

The target request rate is split across multiple worker processes
automatically, each running its own asyncio event loop. Usage:

    uv run python scripts/load_test.py --rate 100

Writes one CSV row per request to a timestamped file under results/.
"""

import argparse
import asyncio
import csv
import math
import multiprocessing
import os
import random
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "results"
DEFAULT_MAX_USER_ID = 20_000
# Keep each Python worker light enough to maintain its schedule even when
# responses back up, so aggregate arrivals stay at the target rate.
REQUESTS_PER_SECOND_PER_WORKER = 250


@dataclass
class Result:
    request_index: int
    user_id: int
    status_code: int
    latency_ms: float
    process_ms: float | None
    db_ms: float | None
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


def header_ms(headers: httpx.Headers, name: str) -> float | None:
    value = headers.get(name)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def worker_count_for(rate: float, requests: int) -> int:
    """Choose enough workers to keep each below its sustainable rate."""
    required = math.ceil(rate / REQUESTS_PER_SECOND_PER_WORKER)
    return max(1, min(required, requests, os.cpu_count() or 1))


async def send_request(
    client: httpx.AsyncClient,
    url: str,
    request_index: int,
    user_id: int,
    worker_start: float,
) -> Result:
    started = time.perf_counter()
    started_s = time.time() - worker_start
    process_ms = None
    db_ms = None
    try:
        response = await client.get(url, params={"user_id": user_id})
        status_code = response.status_code
        process_ms = header_ms(response.headers, "x-process-time-ms")
        db_ms = header_ms(response.headers, "x-db-time-ms")
    except httpx.HTTPError:
        status_code = 0
    finished = time.perf_counter()

    return Result(
        request_index=request_index,
        user_id=user_id,
        status_code=status_code,
        latency_ms=(finished - started) * 1000,
        process_ms=process_ms,
        db_ms=db_ms,
        started_s=started_s,
        finished_s=time.time() - worker_start,
    )


def run_worker(
    url: str,
    timeout: float,
    rate: float,
    requests: list[tuple[int, int]],
    ready: Any,
    start: Any,
) -> list[Result]:
    """Run one worker process with its own async event loop."""
    return asyncio.run(
        run_worker_async(url, timeout, rate, requests, ready, start)
    )


async def run_worker_async(
    url: str,
    timeout: float,
    rate: float,
    requests: list[tuple[int, int]],
    ready: Any,
    start: Any,
) -> list[Result]:
    interval = 1.0 / rate
    limits = httpx.Limits()

    async with httpx.AsyncClient(
        limits=limits,
        timeout=timeout,
    ) as client:
        if ready is not None:
            ready.put(1)
            if not start.wait(timeout=30):
                raise RuntimeError("Timed out waiting for synchronized start")

        worker_start = time.time()

        tasks: list[asyncio.Task[Result]] = []
        for offset, (request_index, user_id) in enumerate(requests):
            target = worker_start + offset * interval
            delay = target - time.time()
            if delay > 0:
                await asyncio.sleep(delay)

            tasks.append(
                asyncio.create_task(
                    send_request(
                        client,
                        url,
                        request_index,
                        user_id,
                        worker_start,
                    )
                )
            )

        return await asyncio.gather(*tasks)


def split_requests(
    user_ids: list[int],
    workers: int,
) -> list[list[tuple[int, int]]]:
    """Interleave requests across workers while keeping global indices."""
    return [
        [
            (request_index, user_ids[request_index])
            for request_index in range(worker_index, len(user_ids), workers)
        ]
        for worker_index in range(workers)
    ]


def run_load_test(args: argparse.Namespace) -> list[Result]:
    rng = random.Random(args.seed)
    user_ids = [
        rng.randint(1, args.max_user_id) for _ in range(args.requests)
    ]

    workers = worker_count_for(args.rate, args.requests)
    worker_rate = args.rate / workers
    assignments = split_requests(user_ids, workers)

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%d-%m-%Y_%H-%M")
    name = f"latency_{timestamp}_{args.requests}req_{args.rate:g}rps"
    output = RESULTS_DIR / f"{name}.csv"
    suffix = 2
    while output.exists():
        output = RESULTS_DIR / f"{name}_{suffix}.csv"
        suffix += 1

    print(
        f"Using {workers} worker process(es) at {worker_rate:g} req/s each"
    )

    if workers > 1:
        mp_context = multiprocessing.get_context("fork")
        with multiprocessing.Manager() as manager:
            ready = manager.Queue()
            start = manager.Event()
            with ProcessPoolExecutor(
                max_workers=workers,
                mp_context=mp_context,
            ) as executor:
                futures = [
                    executor.submit(
                        run_worker,
                        args.url,
                        args.timeout,
                        worker_rate,
                        assignment,
                        ready,
                        start,
                    )
                    for assignment in assignments
                ]

                for _ in range(workers):
                    ready.get(timeout=30)
                start.set()

                results: list[Result] = []
                for future in futures:
                    results.extend(future.result())
    else:
        results = run_worker(
            args.url,
            args.timeout,
            worker_rate,
            assignments[0],
            None,
            None,
        )

    results.sort(key=lambda result: result.request_index)
    write_results(results, output)

    successful = [
        result for result in results if 200 <= result.status_code < 300
    ]
    latencies = sorted(result.latency_ms for result in successful)
    process_times = sorted(
        result.process_ms
        for result in successful
        if result.process_ms is not None
    )
    db_times = sorted(
        result.db_ms for result in successful if result.db_ms is not None
    )
    failed = len(results) - len(successful)

    first_start = min(result.started_s for result in results)
    last_start = max(result.started_s for result in results)
    last_finish = max(result.finished_s for result in results)
    arrival_window = max(last_start - first_start, 1e-9)
    arrival_rate = (
        (len(results) - 1) / arrival_window if len(results) > 1 else 0.0
    )
    completion_rate = len(results) / last_finish if last_finish > 0 else 0.0

    print(
        f"Requests: {len(results)} "
        f"(successful: {len(successful)}, failed: {failed})"
    )
    print(f"Target rate: {args.rate:g} req/s")
    print(
        f"Arrival rate: {arrival_rate:.1f} req/s "
        f"(requests started over {arrival_window:.2f}s)"
    )
    print(
        f"Completion throughput: {completion_rate:.1f} req/s "
        f"(last response after {last_finish:.2f}s)"
    )

    if latencies:
        print_latency_stats("Client latency", latencies)
    if process_times:
        print_latency_stats("Server process", process_times)
    if db_times:
        print_latency_stats("DB query", db_times)

    print(f"Results written to {output}")
    return results


def print_latency_stats(label: str, values: list[float]) -> None:
    print(
        f"{label} (ms): "
        f"min={values[0]:.1f}, "
        f"mean={sum(values) / len(values):.1f}, "
        f"p50={percentile(values, 0.50):.1f}, "
        f"p95={percentile(values, 0.95):.1f}, "
        f"p99={percentile(values, 0.99):.1f}, "
        f"max={values[-1]:.1f}"
    )


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
                "process_ms",
                "db_ms",
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
                    (
                        f"{result.process_ms:.3f}"
                        if result.process_ms is not None
                        else ""
                    ),
                    (
                        f"{result.db_ms:.3f}"
                        if result.db_ms is not None
                        else ""
                    ),
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
    run_load_test(parse_args())
