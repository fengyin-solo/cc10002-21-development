"""协作域接口模型。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Position(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1)
    h: int = Field(ge=1)


class WidgetIn(BaseModel):
    widget_key: str | None = None
    title: str
    type: str
    position: Position
    config: dict[str, Any] = Field(default_factory=dict)


class DashboardCreate(BaseModel):
    title: str


class WidgetAdd(BaseModel):
    base_revision: int
    widget: WidgetIn


class DraftSubmit(BaseModel):
    base_revision: int
    widgets: list[dict[str, Any]]
    change_summary: str | None = None


class ConflictResolution(BaseModel):
    base_revision: int
    widgets: list[dict[str, Any]]


class AccessScopeIn(BaseModel):
    type: str = "workspace"
    members: list[str] | None = None


class PublishPayload(BaseModel):
    idempotency_key: str | None = None
    change_note: str | None = None
    access_scope: AccessScopeIn = Field(default_factory=AccessScopeIn)


class ShareTokenCreate(BaseModel):
    expires_at: str | None = None


class ReportCreate(BaseModel):
    name: str


class ReportLock(BaseModel):
    dashboard_id: int
    version_no: int
