"""Response schema for the offers endpoint."""

from pydantic import BaseModel


class OffersResponse(BaseModel):
    user_id: int
    app_ids: list[int]
