"""HTTP routes."""

from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends

from base.db import get_pool
from core.schema import OffersRequest, OffersResponse
from core.service import fetch_installed_app_ids, filter_uninstalled_app_ids

router = APIRouter()


@router.get("/offers", response_model=OffersResponse)
async def get_offers(
    payload: OffersRequest,
    user_id: int,
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> OffersResponse:
    """Return candidate apps the user has not installed yet."""
    installed_app_ids = await fetch_installed_app_ids(pool, user_id)
    return OffersResponse(
        user_id=user_id,
        app_ids=filter_uninstalled_app_ids(payload.app_ids, installed_app_ids),
    )
