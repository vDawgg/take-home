"""Offer application logic."""

import json
from pathlib import Path

import asyncpg

APP_IDS_PATH = Path(__file__).resolve().parents[1] / "app_ids.json"


def load_candidate_app_ids(path: Path = APP_IDS_PATH) -> list[int]:
    """Load the fixed candidate app IDs used for every offers request."""
    with path.open() as file:
        return json.load(file)


async def fetch_installed_app_ids(pool: asyncpg.Pool, user_id: int) -> set[int]:
    """Return the app IDs the user has already installed."""
    rows = await pool.fetch(
        "SELECT app_id FROM user_installs WHERE user_id = $1",
        user_id,
    )
    return {row["app_id"] for row in rows}


def filter_uninstalled_app_ids(
    candidate_app_ids: list[int],
    installed_app_ids: set[int],
) -> list[int]:
    """Preserve candidate order while dropping already-installed apps."""
    return [
        app_id for app_id in candidate_app_ids if app_id not in installed_app_ids
    ]
