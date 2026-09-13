"""Project and Source schemas."""

from __future__ import annotations

from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict, Field


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    status: str
    created_at: str
    updated_at: str
    source_count: int = 0
    clip_count: int = 0


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]
    total: int


class AddSourceRequest(BaseModel):
    source_type: Literal["url", "upload"] = "upload"
    url: Optional[str] = None


class SourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_type: str
    url: Optional[str]
    filename: Optional[str]
    file_size: Optional[int]
    status: str
    created_at: str


class RightsConfirmationRequest(BaseModel):
    content_type: Literal["user_owned", "user_uploaded", "licensed", "unknown"] = "user_uploaded"
    confirmation_text: str = "I confirm that I own this content or have permission/license to process and repurpose it."
    confirmed: bool = True


class RightsRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    content_type: str
    confirmation_text: str
    confirmed: bool
    confirmed_at: Optional[str]


class ProcessProjectRequest(BaseModel):
    """Trigger full pipeline processing."""
    clip_min_duration: int = 30
    clip_max_duration: int = 90
    max_candidates: int = 50
    caption_style: str = "clean"
    target_aspect_ratio: str = "9:16"
