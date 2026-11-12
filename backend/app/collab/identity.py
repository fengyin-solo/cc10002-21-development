"""本地身份与工作空间上下文。

不接入任何外部身份服务：身份由请求头 ``X-User-Id`` 显式声明，
服务端用本地 users 表校验，并在每次请求时实时检查成员关系。
因此撤销成员权限后，该用户之后的读取和提交都会立刻被拒绝，
前端是否隐藏按钮不影响服务端裁决。
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header

from app.collab.errors import AuthError, ForbiddenError
from app.collab.store import collab_store

EDITOR = "editor"
VIEWER = "viewer"


@dataclass(frozen=True)
class Principal:
    user_id: str
    display_name: str
    workspace_id: str
    role: str

    @property
    def is_editor(self) -> bool:
        return self.role == EDITOR


def resolve_principal(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
) -> Principal:
    """从请求头解析调用方身份并实时校验工作空间成员资格。"""
    if not x_user_id or not x_workspace_id:
        raise AuthError("缺少本地身份或工作空间请求头（X-User-Id / X-Workspace-Id）")
    user = collab_store.users.get(x_user_id)
    if user is None:
        # 不回显用户提交的 ID 之外的任何信息
        raise AuthError(f"本地身份 {x_user_id} 不存在")
    if x_workspace_id not in collab_store.workspaces:
        raise AuthError(f"工作空间 {x_workspace_id} 不存在")
    membership = collab_store.memberships.get((x_workspace_id, x_user_id))
    if membership is None or not membership.get("active", False):
        # 非成员与已撤销成员同等待遇：无权进入该空间
        raise ForbiddenError("当前身份不是该工作空间的有效成员，访问已被拒绝")
    return Principal(
        user_id=x_user_id,
        display_name=user["display_name"],
        workspace_id=x_workspace_id,
        role=membership["role"],
    )


def require_editor(principal: Principal) -> None:
    if not principal.is_editor:
        raise ForbiddenError("只读成员只能查看本空间已发布布局，不能维护草稿或执行发布")
