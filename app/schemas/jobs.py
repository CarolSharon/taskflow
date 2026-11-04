from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JobCreate(BaseModel):
    job_type: str = Field(min_length=1, max_length=100)
    payload: dict[str, Any]
    idempotency_key: str | None = Field(default=None, max_length=255)


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_type: str
    payload: dict[str, Any]
    status: str
    idempotency_key: str | None
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime