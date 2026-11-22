"""Request and response schemas for the offers endpoint."""

from pydantic import BaseModel


class OffersRequest(BaseModel):
    app_ids: list[int]


class OffersResponse(BaseModel):
    user_id: int
    app_ids: list[int]
