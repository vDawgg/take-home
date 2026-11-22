"""HTTP routes."""

from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, Request

from base.db import get_pool
from core.schema import OffersResponse
from core.service import fetch_installed_app_ids, filter_uninstalled_app_ids

router = APIRouter()


def get_candidate_app_ids(request: Request) -> list[int]:
    """Return the candidate app IDs loaded during application startup."""
    return request.app.state.candidate_app_ids


@router.get("/offers", response_model=OffersResponse)
async def get_offers(
    user_id: int,
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    candidate_app_ids: Annotated[list[int], Depends(get_candidate_app_ids)],
) -> OffersResponse:
    """Return candidate apps the user has not installed yet."""
    installed_app_ids = await fetch_installed_app_ids(pool, user_id)
    return OffersResponse(
        user_id=user_id,
        app_ids=filter_uninstalled_app_ids(candidate_app_ids, installed_app_ids),
    )
