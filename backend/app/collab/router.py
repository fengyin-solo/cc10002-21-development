"""布局协作域路由。

身份与工作空间通过请求头声明（X-User-Id / X-Workspace-Id），
每个受保护接口都依赖 resolve_principal 做服务端实时鉴权，
路由层不做业务裁决，只搬运参数与翻译错误码。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.collab.identity import Principal, resolve_principal
from app.collab.schemas import (
    ConflictResolution,
    DashboardCreate,
    DraftSubmit,
    PublishPayload,
    ReportCreate,
    ReportLock,
    ShareTokenCreate,
    WidgetAdd,
)
from app.collab.service import CollabService

router = APIRouter(prefix="/api/collab", tags=["布局协作"])
service = CollabService()


# ---- 身份与工作空间 ----

@router.get("/me")
def whoami(principal: Principal = Depends(resolve_principal)) -> dict:
    return service.whoami(principal)


@router.get("/workspaces")
def my_workspaces(principal: Principal = Depends(resolve_principal)) -> dict:
    return {"items": service.list_my_workspaces(principal)}


@router.get("/members")
def list_members(principal: Principal = Depends(resolve_principal)) -> dict:
    return {"items": service.list_members(principal)}


@router.post("/members/{user_id}/revoke")
def revoke_member(user_id: str, principal: Principal = Depends(resolve_principal)) -> dict:
    return service.revoke_membership(principal, user_id)


@router.post("/members/{user_id}/restore")
def restore_member(user_id: str, principal: Principal = Depends(resolve_principal)) -> dict:
    return service.restore_membership(principal, user_id)


# ---- 看板与草稿 ----

@router.get("/dashboards")
def list_dashboards(principal: Principal = Depends(resolve_principal)) -> dict:
    return {"items": service.list_dashboards(principal)}


@router.post("/dashboards")
def create_dashboard(payload: DashboardCreate, principal: Principal = Depends(resolve_principal)) -> dict:
    return service.create_dashboard(principal, payload.title)


@router.get("/dashboards/{dashboard_id}/draft")
def get_draft(dashboard_id: int, principal: Principal = Depends(resolve_principal)) -> dict:
    return service.get_draft(principal, dashboard_id)


@router.post("/dashboards/{dashboard_id}/widgets")
def add_widget(dashboard_id: int, payload: WidgetAdd, principal: Principal = Depends(resolve_principal)) -> dict:
    return service.add_widget(
        principal,
        dashboard_id,
        payload.widget.model_dump(),
        base_revision=payload.base_revision,
    )


@router.put("/dashboards/{dashboard_id}/draft")
def submit_draft(dashboard_id: int, payload: DraftSubmit, principal: Principal = Depends(resolve_principal)) -> dict:
    return service.submit_draft(principal, dashboard_id, payload.model_dump())


@router.post("/dashboards/{dashboard_id}/conflict-resolution")
def resolve_conflict(dashboard_id: int, payload: ConflictResolution, principal: Principal = Depends(resolve_principal)) -> dict:
    return service.resolve_conflict(principal, dashboard_id, payload.model_dump())


# ---- 发布与版本 ----

@router.post("/dashboards/{dashboard_id}/publish")
def publish(dashboard_id: int, payload: PublishPayload, principal: Principal = Depends(resolve_principal)) -> dict:
    return service.publish(principal, dashboard_id, payload.model_dump(exclude_none=True))


@router.get("/dashboards/{dashboard_id}/versions")
def list_versions(dashboard_id: int, principal: Principal = Depends(resolve_principal)) -> dict:
    return {"items": service.list_versions(principal, dashboard_id)}


@router.get("/dashboards/{dashboard_id}/versions/{version_no}")
def get_version(dashboard_id: int, version_no: int, principal: Principal = Depends(resolve_principal)) -> dict:
    return service.get_version(principal, dashboard_id, version_no)


@router.get("/dashboards/{dashboard_id}/published/latest")
def latest_published(dashboard_id: int, principal: Principal = Depends(resolve_principal)) -> dict:
    return service.get_latest_published(principal, dashboard_id)


@router.post("/dashboards/{dashboard_id}/versions/{version_no}/share-tokens")
def create_share_token(
    dashboard_id: int,
    version_no: int,
    payload: ShareTokenCreate,
    principal: Principal = Depends(resolve_principal),
) -> dict:
    return service.create_share_token(principal, dashboard_id, version_no, payload.model_dump(exclude_none=True))


@router.delete("/share-tokens/{token}")
def revoke_share_token(token: str, principal: Principal = Depends(resolve_principal)) -> dict:
    return service.revoke_share_token(principal, token)


@router.get("/shared/{token}")
def read_shared(token: str) -> dict:
    """分享凭据入口：无需工作空间身份，也只能读到被授权的那一版只读快照。"""
    return service.get_shared_version(token)


# ---- 报告与版本锁定 ----

@router.get("/reports")
def list_reports(principal: Principal = Depends(resolve_principal)) -> dict:
    return {"items": service.list_reports(principal)}


@router.post("/reports")
def create_report(payload: ReportCreate, principal: Principal = Depends(resolve_principal)) -> dict:
    return service.create_report(principal, payload.name)


@router.post("/reports/{report_id}/lock")
def lock_report(report_id: int, payload: ReportLock, principal: Principal = Depends(resolve_principal)) -> dict:
    return service.lock_report(principal, report_id, payload.dashboard_id, payload.version_no)


@router.get("/reports/{report_id}")
def get_report(report_id: int, principal: Principal = Depends(resolve_principal)) -> dict:
    return service.get_report(principal, report_id)


# ---- 测试支持：安排一次发布中断，验证事务回滚 ----

@router.post("/test/arm-publish-failure")
def arm_publish_failure(principal: Principal = Depends(resolve_principal)) -> dict:
    service.arm_publish_failure(principal)
    return {"ok": True, "message": "下一次发布会在固定访问范围前中断并回滚"}
