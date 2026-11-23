"""HTTP routes."""

import time
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, Request, Response

from base.db import get_pool
from core.schema import OffersResponse
from core.service import get_filtered_app_ids

router = APIRouter()


def get_candidate_app_ids(request: Request) -> list[int]:
    """Return the candidate app IDs loaded during application startup."""
    return request.app.state.candidate_app_ids


@router.get("/offers", response_model=OffersResponse)
async def get_offers(
    user_id: int,
    response: Response,
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    candidate_app_ids: Annotated[list[int], Depends(get_candidate_app_ids)],
) -> OffersResponse:
    """Return candidate apps the user has not installed yet."""
    started = time.perf_counter()
    app_ids, cache_hit = await get_filtered_app_ids(
        pool,
        user_id,
        candidate_app_ids,
    )
    db_elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-DB-Time-Ms"] = f"{db_elapsed_ms:.3f}"
    response.headers["X-Cache"] = "HIT" if cache_hit else "MISS"

    return OffersResponse(user_id=user_id, app_ids=app_ids)
