"""Seed the database with mock user install data.

Creates the `user_installs` table (if needed) and streams 1,000,000
(user_id, app_id) pairs into it using PostgreSQL's binary COPY. If the table
already holds the expected number of rows, seeding is skipped, so restarting
the database container does not refill it.

Usage:
    uv run python seed.py [--force]

DATABASE_URL is read from the .env file.
"""

import argparse
import asyncio
import os
import random
import time
from collections.abc import Iterator

import asyncpg
from dotenv import load_dotenv

load_dotenv()

USER_COUNT = 20_000
TOTAL_ROWS = 1_000_000
APP_COUNT = 10_000
INSTALL_STDDEV = 10
MAX_INSTALLS_PER_USER = 200
RANDOM_SEED = 42


def build_install_counts(rng: random.Random) -> list[int]:
    """Return one install count per user, summing exactly to TOTAL_ROWS.

    Counts vary around the mean (TOTAL_ROWS / USER_COUNT) following a normal
    distribution, then get nudged until the total is exact.
    """
    mean = TOTAL_ROWS / USER_COUNT
    max_count = min(APP_COUNT, MAX_INSTALLS_PER_USER)
    if not 1 <= mean <= max_count:
        raise ValueError(
            f"Average installs ({mean:.2f}) must be between 1 and {max_count}"
        )

    counts = [
        max(1, min(max_count, round(rng.gauss(mean, INSTALL_STDDEV))))
        for _ in range(USER_COUNT)
    ]

    delta = TOTAL_ROWS - sum(counts)
    index = 0
    while delta:
        if delta > 0 and counts[index] < max_count:
            counts[index] += 1
            delta -= 1
        elif delta < 0 and counts[index] > 1:
            counts[index] -= 1
            delta += 1
        index = (index + 1) % USER_COUNT

    return counts


def generate_installs(
    counts: list[int], rng: random.Random
) -> Iterator[tuple[int, int]]:
    """Stream distinct (user_id, app_id) pairs without materializing them."""
    app_ids = range(1, APP_COUNT + 1)
    for user_id, install_count in enumerate(counts, start=1):
        for app_id in rng.sample(app_ids, install_count):
            yield user_id, app_id


async def seed(database_url: str, force: bool = False) -> None:
    counts = build_install_counts(random.Random(RANDOM_SEED))
    total_rows = sum(counts)
    rng = random.Random(RANDOM_SEED + 1)

    conn = await asyncpg.connect(database_url)
    try:
        table_exists = await conn.fetchval(
            "SELECT to_regclass('public.user_installs') IS NOT NULL"
        )
        if table_exists and not force:
            stored_rows = await conn.fetchval("SELECT count(*) FROM user_installs")
            if stored_rows == total_rows:
                print(f"user_installs already has {stored_rows:,} rows; skipping seed")
                return

        print(
            f"Seeding {total_rows:,} installs for {USER_COUNT:,} users "
            f"across {APP_COUNT:,} apps "
            f"(min {min(counts)}, max {max(counts)}, "
            f"avg {total_rows / USER_COUNT:.1f})"
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_installs (
                user_id BIGINT NOT NULL,
                app_id INTEGER NOT NULL
            )
            """
        )
        await conn.execute("TRUNCATE user_installs")

        started = time.perf_counter()
        await conn.copy_records_to_table(
            "user_installs",
            records=generate_installs(counts, rng),
            columns=("user_id", "app_id"),
        )
        elapsed = time.perf_counter() - started

        stored_rows = await conn.fetchval("SELECT count(*) FROM user_installs")
    finally:
        await conn.close()

    if stored_rows != total_rows:
        raise RuntimeError(f"Expected {total_rows:,} rows, found {stored_rows:,}")

    print(
        f"Copied {stored_rows:,} rows in {elapsed:.2f}s "
        f"({stored_rows / elapsed:,.0f} rows/s)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the user_installs table.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="truncate and reseed even if the table is already populated",
    )
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit(
            "DATABASE_URL is not set. Add it to a .env file in the project root."
        )

    asyncio.run(seed(database_url, force=args.force))


if __name__ == "__main__":
    main()
