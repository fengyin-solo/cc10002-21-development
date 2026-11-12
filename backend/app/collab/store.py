"""协作域内存仓库与事务原语。

设计要点：
- 所有业务表都是独立 list/dict，事务提交前只操作快照副本，失败时整体丢弃；
- 每个工作空间内的看板/报告各自从 1 顺序发号，因此不同空间会出现相同数字 ID，
  归属隔离完全由 workspace_id 字段保证，而不是靠 ID 全局唯一；
- 部件标识（widget_key）在同一看板内全局唯一且永不复用，删除也不回收；
- 已发布版本是追加写的不可变快照，发布后不再随草稿变化。
"""
from __future__ import annotations

import copy
import threading
from collections import defaultdict
from typing import Any, Callable, TypeVar

from app.collab.errors import CollabError, TransactionError

T = TypeVar("T")


class CollabStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        # 本地身份（不连接任何外部身份服务）
        self.users: dict[str, dict[str, Any]] = {}
        # workspace_id -> 工作空间对象（含名称等）
        self.workspaces: dict[str, dict[str, Any]] = {}
        # (workspace_id, user_id) -> 成员关系 {role, active}
        self.memberships: dict[tuple[str, str], dict[str, Any]] = {}
        # 协作看板，键 (workspace_id, dashboard_id)
        self.dashboards: dict[tuple[str, int], dict[str, Any]] = {}
        # 已发布不可变版本，按版本号顺序保存
        self.published_versions: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        # 协作报告，键 (workspace_id, report_id)
        self.reports: dict[tuple[str, int], dict[str, Any]] = {}
        # 分享凭据 token -> 授权对象
        self.share_tokens: dict[str, dict[str, Any]] = {}
        # 各空间内部发号器
        self._dashboard_seq: dict[str, int] = defaultdict(int)
        self._report_seq: dict[str, int] = defaultdict(int)
        self._version_seq: dict[tuple[str, int], int] = defaultdict(int)
        self._widget_seq: dict[tuple[str, int], int] = defaultdict(int)
        self._token_seq: int = 0
        # 故障注入开关：置位后下一次发布会在写入版本后、提交前失败，用于验证事务回滚
        self.fail_next_publish: bool = False

    # ---- 事务 ----------------------------------------------------------
    def transaction(self, fn: Callable[[], T]) -> T:
        """在锁内执行 ``fn``，先在深拷贝快照上操作，全部成功才整体提交。

        任何异常都会丢弃快照，仓库回到调用前状态，并向上抛出 TransactionError。
        """
        with self._lock:
            backup = self._export_state()
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001 - 事务边界需要兜住所有失败
                self._restore_state(backup)
                # 业务错误（输入校验、冲突、权限等）保持原状态码向上抛，
                # 只有意料之外的失败才包装成 500 事务错误，避免回滚掩盖真实语义。
                if isinstance(exc, CollabError):
                    raise
                raise TransactionError(f"事务已回滚：{exc}") from exc
            return result

    def lock(self) -> threading.RLock:
        """供服务层在一个事务内串行化合并逻辑使用。"""
        return self._lock

    def _snapshot(self) -> dict[str, Any]:
        return self._export_state()

    def _export_state(self) -> dict[str, Any]:
        return {
            "users": copy.deepcopy(self.users),
            "workspaces": copy.deepcopy(self.workspaces),
            "memberships": copy.deepcopy(self.memberships),
            "dashboards": copy.deepcopy(self.dashboards),
            "published_versions": copy.deepcopy(self.published_versions),
            "reports": copy.deepcopy(self.reports),
            "share_tokens": copy.deepcopy(self.share_tokens),
            "_dashboard_seq": dict(self._dashboard_seq),
            "_report_seq": dict(self._report_seq),
            "_version_seq": dict(self._version_seq),
            "_widget_seq": dict(self._widget_seq),
            "_token_seq": self._token_seq,
        }

    def _restore_state(self, state: dict[str, Any]) -> None:
        self.users = state["users"]
        self.workspaces = state["workspaces"]
        self.memberships = state["memberships"]
        self.dashboards = state["dashboards"]
        self.published_versions = defaultdict(list, state["published_versions"])
        self.reports = state["reports"]
        self.share_tokens = state["share_tokens"]
        self._dashboard_seq = defaultdict(int, state["_dashboard_seq"])
        self._report_seq = defaultdict(int, state["_report_seq"])
        self._version_seq = defaultdict(int, state["_version_seq"])
        self._widget_seq = defaultdict(int, state["_widget_seq"])
        self._token_seq = state["_token_seq"]
        # fail_next_publish 是测试故障注入开关，不属于业务状态，
        # 不参与快照恢复，避免一次回滚把已消费的故障又带回来。

    # ---- 发号器 --------------------------------------------------------
    def next_dashboard_id(self, workspace_id: str) -> int:
        self._dashboard_seq[workspace_id] += 1
        return self._dashboard_seq[workspace_id]

    def next_report_id(self, workspace_id: str) -> int:
        self._report_seq[workspace_id] += 1
        return self._report_seq[workspace_id]

    def next_version_no(self, workspace_id: str, dashboard_id: int) -> int:
        key = (workspace_id, dashboard_id)
        self._version_seq[key] += 1
        return self._version_seq[key]

    def next_widget_key(self, workspace_id: str, dashboard_id: int) -> str:
        """部件稳定标识：空间+看板内递增、删除不回收。"""
        key = (workspace_id, dashboard_id)
        self._widget_seq[key] += 1
        return f"w{self._widget_seq[key]:04d}"

    def next_token(self) -> str:
        self._token_seq += 1
        # 不可猜测的随机部分 + 序号，纯本地生成，不依赖外部服务
        import secrets

        return f"st-{self._token_seq:04d}-{secrets.token_hex(12)}"


collab_store = CollabStore()
