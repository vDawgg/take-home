"""Offer application logic."""

import asyncpg


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
