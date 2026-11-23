"""Asyncpg pool lifecycle."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import Request


@asynccontextmanager
async def init_db_pool(database_url: str) -> AsyncIterator[asyncpg.Pool]:
    """Create the shared connection pool and yield it for the app lifetime."""
    pool = await asyncpg.create_pool(
        dsn=database_url,
        min_size=int(os.getenv("DB_POOL_MIN_SIZE", "1")),
        max_size=int(os.getenv("DB_POOL_MAX_SIZE", "10")),
    )
    try:
        yield pool
    finally:
        await pool.close()


def get_pool(request: Request) -> asyncpg.Pool:
    """Return the pool created during application startup."""
    return request.app.state.db_pool
