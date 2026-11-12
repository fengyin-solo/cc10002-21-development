"""协作域初始数据：两个工作空间、编辑/只读成员、同 ID 看板与报告。

刻意让 ws-a 与 ws-b 都拥有 dashboard id=1、report id=1，
用来证明归属隔离不能依赖数字 ID 本身。
"""
from __future__ import annotations

from typing import Any

from app.collab.store import CollabStore


def seed_collab(store: CollabStore) -> None:
    # ---- 本地身份 ----------------------------------------------------
    users = {
        "u-alice": {"user_id": "u-alice", "display_name": "阿黎（编辑）"},
        "u-bob": {"user_id": "u-bob", "display_name": "卜岚（编辑）"},
        "u-carol": {"user_id": "u-carol", "display_name": "卡罗（只读）"},
        "u-dave": {"user_id": "u-dave", "display_name": "戴维（另一空间编辑）"},
        "u-erin": {"user_id": "u-erin", "display_name": "伊琳（另一空间只读）"},
    }
    store.users.update(users)

    store.workspaces.update({
        "ws-a": {"workspace_id": "ws-a", "name": "增长分析空间"},
        "ws-b": {"workspace_id": "ws-b", "name": "风控分析空间"},
    })

    memberships = {
        ("ws-a", "u-alice"): {"role": "editor", "active": True},
        ("ws-a", "u-bob"): {"role": "editor", "active": True},
        ("ws-a", "u-carol"): {"role": "viewer", "active": True},
        ("ws-b", "u-dave"): {"role": "editor", "active": True},
        ("ws-b", "u-erin"): {"role": "viewer", "active": True},
        # 阿黎在 ws-b 没有成员关系，用于验证非成员跨空间被拦。
    }
    store.memberships.update(memberships)

    # ---- 两个空间各建一个 id=1 的看板 -------------------------------
    def _dashboard(ws: str, title: str, widgets: list[dict[str, Any]]) -> tuple[str, int]:
        dashboard_id = store.next_dashboard_id(ws)
        key = (ws, dashboard_id)
        for widget in widgets:
            widget["widget_key"] = store.next_widget_key(ws, dashboard_id)
        store.dashboards[key] = {
            "workspace_id": ws,
            "dashboard_id": dashboard_id,
            "title": title,
            "draft": {
                "revision": 1,
                "base_version_no": 0,
                "widgets": widgets,
                "updated_by": "system",
                "updated_at": "2026-11-01T09:00:00",
                "last_change_summary": "初始化草稿",
                "history": [],
            },
            # 最近一次发布所对应的草稿修订号；0 表示从未发布
            "published_revision": 0,
            "created_at": "2026-11-01T09:00:00",
            "revision_snapshots": {"1": [dict(w) for w in widgets]},
            "known_widget_keys": {w["widget_key"] for w in widgets},
        }
        return key

    key_a = _dashboard(
        "ws-a",
        "经营总览看板",
        [
            {"widget_key": "", "title": "日活跃用户", "type": "line", "position": {"x": 0, "y": 0, "w": 6, "h": 4}, "config": {"metric": "dau"}},
            {"widget_key": "", "title": "支付转化率", "type": "bar", "position": {"x": 6, "y": 0, "w": 6, "h": 4}, "config": {"metric": "pay_cvr"}},
            {"widget_key": "", "title": "渠道分布", "type": "pie", "position": {"x": 0, "y": 4, "w": 12, "h": 4}, "config": {"metric": "channel"}},
        ],
    )
    _dashboard(
        "ws-b",
        "风控监控看板",
        [
            {"widget_key": "", "title": "拦截趋势", "type": "line", "position": {"x": 0, "y": 0, "w": 12, "h": 4}, "config": {"metric": "block_trend"}},
            {"widget_key": "", "title": "风险等级分布", "type": "pie", "position": {"x": 0, "y": 4, "w": 12, "h": 4}, "config": {"metric": "risk_level"}},
        ],
    )

    # ws-a 发布一版，供报告锁定与只读成员查看
    version = {
        "workspace_id": "ws-a",
        "dashboard_id": 1,
        "version_no": store.next_version_no("ws-a", 1),
        "revision": 1,
        "widgets": [dict(w) for w in store.dashboards[key_a]["draft"]["widgets"]],
        "access_scope": {"type": "workspace", "workspace_id": "ws-a", "share_tokens": []},
        "published_by": "u-alice",
        "published_at": "2026-11-02T10:00:00",
        "change_note": "首个正式版本",
        "idempotency_key": None,
    }
    store.published_versions[key_a].append(version)
    store.dashboards[key_a]["published_revision"] = 1

    # ws-b 同样发布一版：两个空间都存在 dashboard id=1 + version 1，
    # 归属隔离不能依赖数字 ID。
    key_b = ("ws-b", 1)
    store.published_versions[key_b].append({
        "workspace_id": "ws-b",
        "dashboard_id": 1,
        "version_no": store.next_version_no("ws-b", 1),
        "revision": 1,
        "widgets": [dict(w) for w in store.dashboards[key_b]["draft"]["widgets"]],
        "access_scope": {"type": "workspace", "workspace_id": "ws-b", "share_tokens": []},
        "published_by": "u-dave",
        "published_at": "2026-11-02T11:00:00",
        "change_note": "风控看板首个正式版本",
        "idempotency_key": None,
    })
    store.dashboards[key_b]["published_revision"] = 1

    # ---- 两个空间各建一个 id=1 的报告 -------------------------------
    def _report(ws: str, name: str) -> tuple[str, int]:
        report_id = store.next_report_id(ws)
        store.reports[(ws, report_id)] = {
            "workspace_id": ws,
            "report_id": report_id,
            "name": name,
            # 锁定的 (dashboard_id, version_no)；None 表示尚未锁定
            "lock": None,
            "created_at": "2026-11-01T09:00:00",
            "updated_by": "system",
        }
        return (ws, report_id)

    _report("ws-a", "月度经营分析报告")
    _report("ws-b", "风控周报")
