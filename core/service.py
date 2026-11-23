"""Offer application logic."""

import json
from pathlib import Path

import asyncpg
from cashews import cache

APP_IDS_PATH = Path(__file__).resolve().parents[1] / "app_ids.json"
CACHE_TTL_SECONDS = 1
CACHE_MAX_SIZE = 1024

cache.setup("mem://", size=CACHE_MAX_SIZE)


def load_candidate_app_ids(path: Path = APP_IDS_PATH) -> list[int]:
    """Load the fixed candidate app IDs used for every offers request."""
    with path.open() as file:
        return json.load(file)


async def fetch_installed_app_ids(pool: asyncpg.Pool, user_id: int) -> set[int]:
    """Return the app IDs the user has already installed."""
    app_ids = await pool.fetchval(
        "SELECT app_ids FROM user_installs WHERE user_id = $1",
        user_id,
    )
    return set(app_ids or [])


def filter_app_ids(
    candidate_app_ids: list[int],
    installed_app_ids: set[int],
) -> list[int]:
    """Preserve candidate order while dropping already-installed apps."""
    return [
        app_id for app_id in candidate_app_ids if app_id not in installed_app_ids
    ]


async def get_filtered_app_ids(
    pool: asyncpg.Pool,
    user_id: int,
    candidate_app_ids: list[int],
) -> tuple[list[int], bool]:
    """Return the user's filtered offers and whether they came from cache."""
    cache_key = f"offers:{user_id}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached, True

    installed_app_ids = await fetch_installed_app_ids(pool, user_id)
    app_ids = filter_app_ids(candidate_app_ids, installed_app_ids)
    await cache.set(cache_key, app_ids, expire=CACHE_TTL_SECONDS)
    return app_ids, False
