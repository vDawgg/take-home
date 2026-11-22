"""FastAPI application entry point."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from base.db import init_db_pool
from core.router import router
from core.service import load_candidate_app_ids

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to a .env file in the project root."
        )

    async with init_db_pool(database_url) as pool:
        app.state.db_pool = pool
        app.state.candidate_app_ids = load_candidate_app_ids()
        yield


app = FastAPI(title="Almedia Take Home", lifespan=lifespan)
app.include_router(router)
