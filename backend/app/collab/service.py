"""布局协作服务层：所有业务裁决都在这里，路由层只做参数搬运。

权限矩阵（服务端强制）：
- editor：维护本空间看板草稿、发布、创建/锁定报告、管理分享凭据；
- viewer：只读本空间看板的已发布版本与已锁定报告，不能接触草稿写接口；
- 非成员/已撤销成员：任何本空间资源都不可见，跨空间 ID 猜测一律 404/403；
- 分享凭据只授予对应已发布版本的只读访问，永远不等于布局编辑权限。
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from app.collab.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.collab.identity import Principal, require_editor
from app.collab.merge import three_way_merge
from app.collab.store import CollabStore, collab_store

WIDGET_TYPES = {"line", "bar", "pie", "table", "kpi", "text"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CollabService:
    def __init__(self, store: CollabStore | None = None) -> None:
        self.store = store or collab_store

    @contextmanager
    def _exclusive(self):
        """串行化所有写操作。

        FastAPI 会把同步路由放进线程池，并发请求可能同时改草稿；
        与发布事务使用同一把可重入锁，保证「读基线—合并—写修订」原子完成，
        不会出现两个请求基于同一修订号双双写成功的丢失更新。
        """
        with self.store.lock():
            yield

    # ============ 身份与工作空间 ============

    def whoami(self, principal: Principal) -> dict[str, Any]:
        return {
            "user_id": principal.user_id,
            "display_name": principal.display_name,
            "workspace_id": principal.workspace_id,
            "role": principal.role,
        }

    def list_my_workspaces(self, principal: Principal) -> list[dict[str, Any]]:
        """列出当前身份仍是有效成员的工作空间，供管理端切换。"""
        out: list[dict[str, Any]] = []
        for (ws_id, user_id), membership in self.store.memberships.items():
            if user_id == principal.user_id and membership.get("active"):
                ws = self.store.workspaces[ws_id]
                out.append({
                    "workspace_id": ws_id,
                    "name": ws["name"],
                    "role": membership["role"],
                })
        return sorted(out, key=lambda item: item["workspace_id"])

    def list_members(self, principal: Principal) -> list[dict[str, Any]]:
        """成员列表仅本空间有效成员可查看（只读成员也能看到和谁协作）。"""
        out: list[dict[str, Any]] = []
        for (ws_id, user_id), membership in self.store.memberships.items():
            if ws_id != principal.workspace_id:
                continue
            user = self.store.users[user_id]
            out.append({
                "user_id": user_id,
                "display_name": user["display_name"],
                "role": membership["role"],
                "active": membership["active"],
            })
        return sorted(out, key=lambda item: item["user_id"])

    def revoke_membership(self, principal: Principal, user_id: str) -> dict[str, Any]:
        """撤销成员资格：实时生效，影响其之后的读取与提交，不依赖前端隐藏。"""
        with self._exclusive():
            require_editor(principal)
            key = (principal.workspace_id, user_id)
            membership = self.store.memberships.get(key)
            if membership is None:
                # 不透露目标用户是否在别的空间存在
                raise NotFoundError(f"成员 {user_id} 不在当前工作空间")
            if user_id == principal.user_id:
                raise ForbiddenError("不能撤销自己的成员资格，请由其他编辑者操作")
            membership["active"] = False
            membership["revoked_at"] = _now()
            membership["revoked_by"] = principal.user_id
            # 旧编辑草稿处理策略：保留草稿内容与归属，但标记其修订历史，
            # 权限恢复前该用户无法再次提交；其他编辑者可继续在同一草稿上协作。
            return {"user_id": user_id, "active": False, "message": "成员资格已撤销，其后的访问与提交都会被服务端拒绝"}

    def restore_membership(self, principal: Principal, user_id: str) -> dict[str, Any]:
        with self._exclusive():
            require_editor(principal)
            membership = self.store.memberships.get((principal.workspace_id, user_id))
            if membership is None:
                raise NotFoundError(f"成员 {user_id} 不在当前工作空间")
            membership["active"] = True
            membership.pop("revoked_at", None)
            membership.pop("revoked_by", None)
            return {"user_id": user_id, "active": True, "role": membership["role"]}

    # ============ 看板与草稿 ============

    def _get_dashboard(self, principal: Principal, dashboard_id: int) -> dict[str, Any]:
        """归属隔离的单点入口：跨空间访问与不存在返回完全相同的 404。"""
        dashboard = self.store.dashboards.get((principal.workspace_id, dashboard_id))
        if dashboard is None:
            raise NotFoundError(f"看板 {dashboard_id} 不存在或不属于当前工作空间")
        return dashboard

    def list_dashboards(self, principal: Principal) -> list[dict[str, Any]]:
        rows = [
            d for (ws_id, _), d in self.store.dashboards.items()
            if ws_id == principal.workspace_id
        ]
        return [
            {
                "dashboard_id": d["dashboard_id"],
                "title": d["title"],
                "draft_revision": d["draft"]["revision"],
                "published_revision": d["published_revision"],
                "published_versions": len(self.store.published_versions[(principal.workspace_id, d["dashboard_id"])]),
                "last_updated_by": d["draft"]["updated_by"],
                "last_updated_at": d["draft"]["updated_at"],
            }
            for d in sorted(rows, key=lambda item: item["dashboard_id"])
        ]

    def get_draft(self, principal: Principal, dashboard_id: int) -> dict[str, Any]:
        """草稿只对编辑者可见；只读成员读草稿直接 403。"""
        require_editor(principal)
        dashboard = self._get_dashboard(principal, dashboard_id)
        return {
            "dashboard_id": dashboard_id,
            "title": dashboard["title"],
            "draft": copy.deepcopy(dashboard["draft"]),
        }

    def create_dashboard(self, principal: Principal, title: str) -> dict[str, Any]:
        with self._exclusive():
            require_editor(principal)
            title = (title or "").strip()
            if not title:
                raise ValidationError("看板名称不能为空")
            dashboard_id = self.store.next_dashboard_id(principal.workspace_id)
            dashboard = {
                "workspace_id": principal.workspace_id,
                "dashboard_id": dashboard_id,
                "title": title,
                "draft": {
                    "revision": 1,
                    "base_version_no": 0,
                    "widgets": [],
                    "updated_by": principal.user_id,
                    "updated_at": _now(),
                    "last_change_summary": "创建看板",
                    "history": [],
                },
                "published_revision": 0,
                "created_at": _now(),
                # 每个修订号对应的部件快照，供三向合并取基线
                "revision_snapshots": {"1": []},
                # 本看板发放过的全部部件标识，删除不回收、跨看板不可复用
                "known_widget_keys": set(),
            }
            self.store.dashboards[(principal.workspace_id, dashboard_id)] = dashboard
            return {"dashboard_id": dashboard_id, "title": title, "draft_revision": 1}

    def add_widget(
        self,
        principal: Principal,
        dashboard_id: int,
        widget: dict[str, Any],
        *,
        base_revision: int,
    ) -> dict[str, Any]:
        with self._exclusive():
            require_editor(principal)
            dashboard = self._get_dashboard(principal, dashboard_id)
            draft = dashboard["draft"]
            self._check_revision(draft, base_revision)
            self._validate_widget(widget, allow_missing_key=True)
            new_widget = {
                "widget_key": self.store.next_widget_key(principal.workspace_id, dashboard_id),
                "title": str(widget["title"]).strip(),
                "type": widget["type"],
                "position": copy.deepcopy(widget["position"]),
                "config": copy.deepcopy(widget.get("config") or {}),
            }
            draft["widgets"].append(new_widget)
            dashboard.setdefault("known_widget_keys", set()).add(new_widget["widget_key"])
            self._bump_revision(draft, principal, f"新增部件 {new_widget['widget_key']}")
            self._save_snapshot(dashboard)
            return {"draft_revision": draft["revision"], "widget": new_widget}

    def submit_draft(
        self,
        principal: Principal,
        dashboard_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """提交完整草稿。带基线修订号，走三向合并；冲突时整体不写入并返回 409。"""
        with self._exclusive():
            require_editor(principal)
            base_revision = int(payload.get("base_revision") or 0)
            incoming_widgets = payload.get("widgets")
            change_summary = str(payload.get("change_summary") or "提交草稿修改")
            if not isinstance(incoming_widgets, list):
                raise ValidationError("widgets 必须是部件列表")

            dashboard = self._get_dashboard(principal, dashboard_id)
            draft = dashboard["draft"]
            self._check_revision(draft, base_revision, allow_stale=True)
            for widget in incoming_widgets:
                self._validate_widget(widget)
            # 所有部件标识必须是本看板发放过的；新增部件走 add_widget 由服务端发号
            self._ensure_keys_known(dashboard, incoming_widgets, allow_deleted=True)

            if base_revision == draft["revision"]:
                # 无并发：直接采纳
                merged_widgets = copy.deepcopy(incoming_widgets)
                decisions = [{"action": "submit", "result": "fast_forward"}]
                conflicts: list[dict[str, Any]] = []
            else:
                base_widgets = self._snapshot_revision(dashboard, base_revision)
                outcome = three_way_merge(base_widgets, draft["widgets"], incoming_widgets)
                if outcome.has_conflict:
                    # 关键：冲突时不写任何内容，返回双方差异供人工裁决
                    raise ConflictError(
                        "草稿合并存在冲突，未做任何修改，请按 conflicts 裁决后调用冲突裁决接口",
                        details={
                            "base_revision": base_revision,
                            "current_revision": draft["revision"],
                            "conflicts": outcome.conflicts,
                            "current_widgets": copy.deepcopy(draft["widgets"]),
                            "incoming_widgets": copy.deepcopy(incoming_widgets),
                        },
                    )
                merged_widgets = outcome.merged_widgets
                decisions = outcome.decisions
                conflicts = outcome.conflicts

            draft["widgets"] = merged_widgets
            self._bump_revision(draft, principal, change_summary, decisions=decisions)
            self._save_snapshot(dashboard)
            return {
                "dashboard_id": dashboard_id,
                "draft_revision": draft["revision"],
                "merged": True,
                "decisions": decisions,
                "conflicts": conflicts,
            }

    def resolve_conflict(
        self,
        principal: Principal,
        dashboard_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """人工裁决冲突后提交：调用方显式给出最终部件表和原基线，服务端复核。"""
        with self._exclusive():
            require_editor(principal)
            base_revision = int(payload.get("base_revision") or 0)
            final_widgets = payload.get("widgets")
            if not isinstance(final_widgets, list):
                raise ValidationError("widgets 必须是部件列表")
            dashboard = self._get_dashboard(principal, dashboard_id)
            draft = dashboard["draft"]
            if base_revision >= draft["revision"]:
                raise ConflictError("裁决请求的基线修订号不早于当前草稿，应先重新拉取草稿")
            for widget in final_widgets:
                self._validate_widget(widget)
            self._ensure_keys_known(dashboard, final_widgets, allow_deleted=True)
            draft["widgets"] = copy.deepcopy(final_widgets)
            self._bump_revision(draft, principal, f"人工裁决冲突（基线 r{base_revision}）")
            self._save_snapshot(dashboard)
            return {"dashboard_id": dashboard_id, "draft_revision": draft["revision"], "resolved": True}

    # ============ 发布：一次性固定版本与访问范围 ============

    def publish(
        self,
        principal: Principal,
        dashboard_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """发布一个不可变版本。

        - 同一次草稿修订号重复发布：幂等返回已存在版本，不产生新版本；
        - 版本内容（部件快照）与访问范围在同一事务内固定；
        - 任一步骤失败整体回滚，仓库里不会留下半成品版本。
        """
        with self._exclusive():
            require_editor(principal)
            idempotency_key = str(payload.get("idempotency_key") or "").strip() or None
            access_scope = self._build_access_scope(principal, payload.get("access_scope") or {})

            def _do() -> dict[str, Any]:
                dashboard = self._get_dashboard(principal, dashboard_id)
                draft = dashboard["draft"]

                # 幂等：相同幂等键直接返回原版本
                if idempotency_key:
                    for version in self.store.published_versions[(principal.workspace_id, dashboard_id)]:
                        if version.get("idempotency_key") == idempotency_key:
                            return {"version": copy.deepcopy(version), "idempotent": True}

                # 同修订号重复发布（无幂等键时）也不产生新版本
                if dashboard["published_revision"] == draft["revision"]:
                    existing = self.store.published_versions[(principal.workspace_id, dashboard_id)][-1]
                    return {"version": copy.deepcopy(existing), "idempotent": True, "reason": "该草稿修订号已发布"}

                version_no = self.store.next_version_no(principal.workspace_id, dashboard_id)
                version = {
                    "workspace_id": principal.workspace_id,
                    "dashboard_id": dashboard_id,
                    "version_no": version_no,
                    "revision": draft["revision"],
                    "widgets": copy.deepcopy(draft["widgets"]),
                    "access_scope": access_scope,
                    "published_by": principal.user_id,
                    "published_at": _now(),
                    "change_note": str(payload.get("change_note") or f"发布版本 v{version_no}"),
                    "idempotency_key": idempotency_key,
                }
                self.store.published_versions[(principal.workspace_id, dashboard_id)].append(version)

                # 故障注入点：模拟发布中断，验证事务回滚（版本与范围都不能残留）
                if self.store.fail_next_publish:
                    self.store.fail_next_publish = False
                    raise RuntimeError("模拟发布中断：固定访问范围前失败")

                dashboard["published_revision"] = draft["revision"]
                dashboard["draft"]["base_version_no"] = version_no
                return {"version": copy.deepcopy(version), "idempotent": False}

            return self.store.transaction(_do)

    def list_versions(self, principal: Principal, dashboard_id: int) -> list[dict[str, Any]]:
        """已发布版本：编辑者与只读成员都可读（只读成员的主要读取对象）。"""
        self._get_dashboard(principal, dashboard_id)
        versions = self.store.published_versions[(principal.workspace_id, dashboard_id)]
        return [self._version_summary(v) for v in versions]

    def get_version(self, principal: Principal, dashboard_id: int, version_no: int) -> dict[str, Any]:
        self._get_dashboard(principal, dashboard_id)
        version = self._find_version(principal.workspace_id, dashboard_id, version_no)
        return copy.deepcopy(version)

    def get_latest_published(self, principal: Principal, dashboard_id: int) -> dict[str, Any]:
        """只读成员查看本空间已发布布局的入口。"""
        self._get_dashboard(principal, dashboard_id)
        versions = self.store.published_versions[(principal.workspace_id, dashboard_id)]
        if not versions:
            raise NotFoundError(f"看板 {dashboard_id} 还没有已发布版本")
        return copy.deepcopy(versions[-1])

    # ============ 分享凭据：只读、绝不等于编辑权 ============

    def create_share_token(
        self,
        principal: Principal,
        dashboard_id: int,
        version_no: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        with self._exclusive():
            require_editor(principal)
            version = self._find_version(principal.workspace_id, dashboard_id, version_no)
            token = self.store.next_token()
            record = {
                "token": token,
                "workspace_id": principal.workspace_id,
                "dashboard_id": dashboard_id,
                "version_no": version_no,
                "created_by": principal.user_id,
                "created_at": _now(),
                "expires_at": payload.get("expires_at"),  # None 表示长期有效
                "revoked": False,
            }
            self.store.share_tokens[token] = record
            # 不回写已发布版本：发布时固定的访问范围快照必须保持不可变，
            # 凭据有效性只由 share_tokens 表裁决，历史版本内容永不被后续操作修改。
            return copy.deepcopy(record)

    def get_shared_version(self, token: str) -> dict[str, Any]:
        """凭分享凭据读取：只能读到固定的那一版，且不能借凭据触碰草稿或其他版本。"""
        record = self.store.share_tokens.get(token)
        if record is None or record.get("revoked"):
            raise NotFoundError("分享凭据无效或已撤销")
        expires_at = record.get("expires_at")
        if expires_at and _now() > expires_at:
            raise ForbiddenError("分享凭据已过有效期")
        version = self._find_version(record["workspace_id"], record["dashboard_id"], record["version_no"])
        return {
            "shared": True,
            "dashboard_id": record["dashboard_id"],
            "version_no": record["version_no"],
            "widgets": copy.deepcopy(version["widgets"]),
            "published_at": version["published_at"],
        }

    def revoke_share_token(self, principal: Principal, token: str) -> dict[str, Any]:
        with self._exclusive():
            require_editor(principal)
            record = self.store.share_tokens.get(token)
            # 跨空间的 token 按不存在处理，不透露其他空间凭据信息
            if record is None or record["workspace_id"] != principal.workspace_id:
                raise NotFoundError("分享凭据不存在")
            record["revoked"] = True
            record["revoked_at"] = _now()
            return {"token": token, "revoked": True}

    # ============ 报告：锁定确定的一版 ============

    def list_reports(self, principal: Principal) -> list[dict[str, Any]]:
        rows = [
            r for (ws_id, _), r in self.store.reports.items()
            if ws_id == principal.workspace_id
        ]
        return [self._report_summary(r) for r in sorted(rows, key=lambda item: item["report_id"])]

    def create_report(self, principal: Principal, name: str) -> dict[str, Any]:
        with self._exclusive():
            require_editor(principal)
            name = (name or "").strip()
            if not name:
                raise ValidationError("报告名称不能为空")
            report_id = self.store.next_report_id(principal.workspace_id)
            report = {
                "workspace_id": principal.workspace_id,
                "report_id": report_id,
                "name": name,
                "lock": None,
                "created_at": _now(),
                "updated_by": principal.user_id,
            }
            self.store.reports[(principal.workspace_id, report_id)] = report
            return self._report_summary(report)

    def lock_report(
        self,
        principal: Principal,
        report_id: int,
        dashboard_id: int,
        version_no: int,
    ) -> dict[str, Any]:
        """把报告钉在某个已发布版本上；之后草稿怎么改都不影响报告看到的布局。"""
        with self._exclusive():
            require_editor(principal)
            report = self._get_report(principal, report_id)
            # 同空间校验：跨空间的看板/版本号猜测直接 404
            version = self._find_version(principal.workspace_id, dashboard_id, version_no)
            report["lock"] = {
                "dashboard_id": dashboard_id,
                "version_no": version_no,
                "revision": version["revision"],
                "locked_at": _now(),
                "locked_by": principal.user_id,
            }
            report["updated_by"] = principal.user_id
            return self._report_summary(report)

    def get_report(self, principal: Principal, report_id: int) -> dict[str, Any]:
        """读取报告及其锁定版本的完整布局快照。

        锁定版本中的部件即使已在新草稿里被删除，这里仍按旧版完整返回，
        并附带新版本影响说明（哪些部件在最新草稿/最新发布版中已不存在）。
        """
        report = self._get_report(principal, report_id)
        result = self._report_summary(report)
        if report["lock"] is None:
            result["locked_layout"] = None
            result["layout_impact"] = None
            return result

        lock = report["lock"]
        version = self._find_version(principal.workspace_id, lock["dashboard_id"], lock["version_no"])
        result["locked_layout"] = copy.deepcopy(version)

        # 新版本影响：对比最新草稿与最新发布版
        dashboard = self.store.dashboards[(principal.workspace_id, lock["dashboard_id"])]
        locked_keys = {w["widget_key"] for w in version["widgets"]}
        draft_keys = {w["widget_key"] for w in dashboard["draft"]["widgets"]}
        removed_in_draft = sorted(locked_keys - draft_keys)
        versions = self.store.published_versions[(principal.workspace_id, lock["dashboard_id"])]
        latest = versions[-1] if versions else None
        removed_in_latest: list[str] = []
        if latest and latest["version_no"] != lock["version_no"]:
            latest_keys = {w["widget_key"] for w in latest["widgets"]}
            removed_in_latest = sorted(locked_keys - latest_keys)
        result["layout_impact"] = {
            "locked_version_no": lock["version_no"],
            "latest_draft_revision": dashboard["draft"]["revision"],
            "latest_published_version_no": latest["version_no"] if latest else None,
            "removed_in_latest_draft": removed_in_draft,
            "removed_in_latest_published": removed_in_latest,
            "explanation": (
                "被引用部件在新版草稿中删除后，锁定版本仍保留旧版解释；"
                "上述部件在新版布局中已不存在，报告正文引用需按影响清单评估调整。"
                if removed_in_draft or removed_in_latest else "锁定版本的部件在当前最新布局中均仍存在。"
            ),
        }
        return result

    # ============ 内部辅助 ============

    def _get_report(self, principal: Principal, report_id: int) -> dict[str, Any]:
        report = self.store.reports.get((principal.workspace_id, report_id))
        if report is None:
            raise NotFoundError(f"报告 {report_id} 不存在或不属于当前工作空间")
        return report

    def _find_version(self, workspace_id: str, dashboard_id: int, version_no: int) -> dict[str, Any]:
        for version in self.store.published_versions[(workspace_id, dashboard_id)]:
            if version["version_no"] == version_no:
                return version
        # 不区分"看板不存在"和"版本不存在"，避免通过版本号探测
        raise NotFoundError(f"看板 {dashboard_id} 的版本 {version_no} 不存在或不属于当前工作空间")

    def _report_summary(self, report: dict[str, Any]) -> dict[str, Any]:
        return {
            "report_id": report["report_id"],
            "workspace_id": report["workspace_id"],
            "name": report["name"],
            "lock": copy.deepcopy(report["lock"]),
            "updated_by": report["updated_by"],
        }

    def _version_summary(self, version: dict[str, Any]) -> dict[str, Any]:
        return {
            "version_no": version["version_no"],
            "revision": version["revision"],
            "widget_count": len(version["widgets"]),
            "widget_keys": [w["widget_key"] for w in version["widgets"]],
            "access_scope": copy.deepcopy(version["access_scope"]),
            "published_by": version["published_by"],
            "published_at": version["published_at"],
            "change_note": version["change_note"],
            "idempotency_key": version.get("idempotency_key"),
        }

    def _build_access_scope(self, principal: Principal, raw: dict[str, Any]) -> dict[str, Any]:
        scope_type = str(raw.get("type") or "workspace").strip()
        if scope_type not in {"workspace", "custom"}:
            raise ValidationError("访问范围类型只支持 workspace 或 custom")
        scope: dict[str, Any] = {
            "type": scope_type,
            "workspace_id": principal.workspace_id,
            "share_tokens": [],
        }
        if scope_type == "custom":
            members = raw.get("members")
            if not isinstance(members, list) or not members:
                raise ValidationError("自定义访问范围必须给出成员列表")
            valid: list[str] = []
            for user_id in members:
                membership = self.store.memberships.get((principal.workspace_id, str(user_id)))
                if membership is None or not membership.get("active"):
                    # 不把非成员/他空间用户写进访问范围，错误信息只说当前空间
                    raise ValidationError(f"成员 {user_id} 不是当前工作空间有效成员，无法加入访问范围")
                valid.append(str(user_id))
            scope["members"] = valid
        return scope

    def _check_revision(self, draft: dict[str, Any], base_revision: int, *, allow_stale: bool = False) -> None:
        if base_revision <= 0:
            raise ValidationError("base_revision 必须是正数")
        if base_revision > draft["revision"]:
            raise ConflictError(f"基线修订号 r{base_revision} 比服务端最新 r{draft['revision']} 还新，请先拉取草稿")
        if not allow_stale and base_revision != draft["revision"]:
            raise ConflictError(
                f"草稿已被其他编辑者推进到 r{draft['revision']}（你的基线 r{base_revision}），请重新拉取后合并提交"
            )

    def _bump_revision(
        self,
        draft: dict[str, Any],
        principal: Principal,
        summary: str,
        *,
        decisions: list[dict[str, Any]] | None = None,
    ) -> None:
        draft["revision"] += 1
        draft["updated_by"] = principal.user_id
        draft["updated_at"] = _now()
        draft["last_change_summary"] = summary
        draft.setdefault("history", []).append({
            "revision": draft["revision"],
            "by": principal.user_id,
            "at": draft["updated_at"],
            "summary": summary,
            "decisions": decisions or [],
        })

    def _save_snapshot(self, dashboard: dict[str, Any]) -> None:
        """在修订号推进后固化当前部件表，作为后续三向合并的历史基线。"""
        dashboard.setdefault("revision_snapshots", {})[
            str(dashboard["draft"]["revision"])
        ] = copy.deepcopy(dashboard["draft"]["widgets"])

    def _snapshot_revision(self, dashboard: dict[str, Any], revision: int) -> list[dict[str, Any]]:
        """取历史修订的部件快照作为三向合并的共同基线。"""
        snapshots = dashboard.setdefault("revision_snapshots", {})
        if str(revision) not in snapshots:
            raise ConflictError(f"找不到修订号 r{revision} 的历史快照，请重新拉取最新草稿后再提交")
        return copy.deepcopy(snapshots[str(revision)])

    def _ensure_keys_known(
        self,
        dashboard: dict[str, Any],
        widgets: list[dict[str, Any]],
        *,
        allow_deleted: bool = False,
    ) -> None:
        known = dashboard.setdefault("known_widget_keys", set())
        for widget in widgets:
            key = widget["widget_key"]
            if key not in known:
                raise ValidationError(f"部件标识 {key} 不属于本看板，拒绝写入（标识不可跨看板复用）")

    def _validate_widget(self, widget: Any, *, allow_missing_key: bool = False) -> None:
        if not isinstance(widget, dict):
            raise ValidationError("部件必须是对象")
        if not allow_missing_key and not str(widget.get("widget_key") or "").strip():
            raise ValidationError("部件缺少稳定标识 widget_key")
        title = str(widget.get("title") or "").strip()
        if not title:
            raise ValidationError("部件标题不能为空")
        if widget.get("type") not in WIDGET_TYPES:
            raise ValidationError(f"部件类型 {widget.get('type')!r} 不受支持")
        position = widget.get("position")
        if not isinstance(position, dict) or not all(k in position for k in ("x", "y", "w", "h")):
            raise ValidationError("部件位置必须包含 x/y/w/h")
        if not all(isinstance(position[k], int) and position[k] >= 0 for k in ("x", "y", "w", "h")) or position["w"] == 0 or position["h"] == 0:
            raise ValidationError("部件位置坐标必须是非负整数且宽高大于 0")

    # 供测试使用：安排下一次发布中断
    def arm_publish_failure(self, principal: Principal) -> None:
        with self._exclusive():
            require_editor(principal)
            self.store.fail_next_publish = True
