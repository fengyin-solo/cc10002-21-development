"""草稿三向合并引擎。

场景：两个编辑者基于同一草稿修订号 R 各自修改，先提交者把草稿推进到 R+1，
后提交者仍带着 base_revision=R。服务端不能用后一次请求整体覆盖前一次，
而是对三份布局做按部件的三向合并：

- base：共同基线修订 R 的部件表
- current：服务端最新草稿（已包含先提交者的改动）
- incoming：后提交者提交的完整部件表

裁决规则（每个 widget_key 独立判定，可解释）：
1. 仅一侧新增/删除：接受该侧改动；
2. 两侧都删除：保持删除；
3. 一侧删除、另一侧修改同一部件：冲突 CONFLICT_DELETE_UPDATE；
4. 两侧都修改同一部件：
   - 修改内容完全一致：视为相同改动，直接采纳；
   - 修改字段互不重叠：自动合并，各自改动都保留；
   - 修改了同一字段且取值不同：冲突 CONFLICT_FIELD，逐字段列出；
5. 位置（position）与标题、配置分开比对，移动和改配置可自动合并。

冲突不猜测、不静默覆盖，整体返回 409 并附双方差异，由调用方显式裁决后重新提交。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from app.collab.errors import ConflictError

# 合并结果标签
AUTO_MERGED = "auto_merged"
CONFLICT_DELETE_UPDATE = "conflict_delete_update"
CONFLICT_FIELD = "conflict_field"


@dataclass
class MergeOutcome:
    merged_widgets: list[dict[str, Any]]
    decisions: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_conflict(self) -> bool:
        return bool(self.conflicts)


def _index(widgets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for widget in widgets:
        key = widget["widget_key"]
        if key in indexed:
            raise ConflictError(f"提交内容里部件标识 {key} 重复，无法合并")
        indexed[key] = widget
    return indexed


def _changed_fields(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    """返回 after 相对 before 发生变化的字段（浅比较，position/config 整体作为字段）。"""
    if before is None or after is None:
        return {}
    changed: dict[str, Any] = {}
    for field_name in ("title", "type", "position", "config"):
        if before.get(field_name) != after.get(field_name):
            changed[field_name] = {"base": before.get(field_name), "theirs": after.get(field_name)}
    return changed


def three_way_merge(
    base: list[dict[str, Any]],
    current: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> MergeOutcome:
    base_map = _index(base)
    current_map = _index(current)
    incoming_map = _index(incoming)

    all_keys = list(dict.fromkeys([*base_map.keys(), *current_map.keys(), *incoming_map.keys()]))
    merged: dict[str, dict[str, Any]] = {}
    decisions: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []

    for key in all_keys:
        b = base_map.get(key)
        c = current_map.get(key)
        i = incoming_map.get(key)
        current_changed = b is not None and c is not None and c != b
        incoming_changed = b is not None and i is not None and i != b
        current_deleted = b is not None and c is None
        incoming_deleted = b is not None and i is None
        current_added = b is None and c is not None
        incoming_added = b is None and i is not None

        # 1/2. 新增
        if b is None:
            if current_added and incoming_added:
                if c == i:
                    merged[key] = copy.deepcopy(c)
                    decisions.append({"widget_key": key, "action": "add", "result": "identical_add"})
                else:
                    # 同一个新 key 双方都建了但内容不同：key 由服务端发放，正常不会出现，
                    # 一旦出现按字段冲突处理。
                    field_conflicts = _field_conflicts(c, i)
                    if field_conflicts:
                        conflicts.append({
                            "widget_key": key, "kind": CONFLICT_FIELD,
                            "reason": "双方新增了同一标识但字段取值不同", "fields": field_conflicts,
                        })
                    else:
                        merged[key] = copy.deepcopy(i)
                continue
            if current_added:
                merged[key] = copy.deepcopy(c)
                decisions.append({"widget_key": key, "action": "add", "result": "kept_current_add"})
                continue
            if incoming_added:
                merged[key] = copy.deepcopy(i)
                decisions.append({"widget_key": key, "action": "add", "result": "accepted_incoming_add"})
                continue

        # 3. 删除相关
        if current_deleted or incoming_deleted:
            if current_deleted and incoming_deleted:
                decisions.append({"widget_key": key, "action": "delete", "result": "both_deleted"})
                continue
            if current_deleted and incoming_changed:
                conflicts.append({
                    "widget_key": key, "kind": CONFLICT_DELETE_UPDATE,
                    "reason": "对方已删除该部件，而你的提交修改了它",
                    "incoming_changes": _changed_fields(b, i),
                })
                continue
            if incoming_deleted and current_changed:
                conflicts.append({
                    "widget_key": key, "kind": CONFLICT_DELETE_UPDATE,
                    "reason": "你删除了该部件，但对方已经修改了它",
                    "current_changes": _changed_fields(b, c),
                })
                continue
            if current_deleted:
                decisions.append({"widget_key": key, "action": "delete", "result": "kept_current_delete"})
                continue
            decisions.append({"widget_key": key, "action": "delete", "result": "accepted_incoming_delete"})
            continue

        # 4. 双方都还在：修改合并
        if not current_changed and not incoming_changed:
            merged[key] = copy.deepcopy(c)
            decisions.append({"widget_key": key, "action": "keep", "result": "unchanged"})
            continue
        if current_changed and not incoming_changed:
            merged[key] = copy.deepcopy(c)
            decisions.append({"widget_key": key, "action": "update", "result": "kept_current_change"})
            continue
        if incoming_changed and not current_changed:
            merged[key] = copy.deepcopy(i)
            decisions.append({"widget_key": key, "action": "update", "result": "accepted_incoming_change"})
            continue

        # 双方都修改：按字段做三向判定，只有双方都改了同一字段且取值不同才算冲突
        if c == i:
            merged[key] = copy.deepcopy(c)
            decisions.append({"widget_key": key, "action": "update", "result": "identical_change"})
            continue
        combined = copy.deepcopy(b)
        field_conflicts: list[dict[str, Any]] = []
        for field_name in ("title", "type", "position", "config"):
            base_val = b.get(field_name)
            current_val = c.get(field_name)
            incoming_val = i.get(field_name)
            current_touched = base_val != current_val
            incoming_touched = base_val != incoming_val
            if current_touched and incoming_touched and current_val != incoming_val:
                # 双方都动了同一字段且给出不同值：无法猜测，列为冲突
                field_conflicts.append({
                    "field": field_name,
                    "base": base_val,
                    "current": current_val,
                    "incoming": incoming_val,
                })
            elif current_touched:
                combined[field_name] = copy.deepcopy(current_val)
            elif incoming_touched:
                combined[field_name] = copy.deepcopy(incoming_val)
            else:
                combined[field_name] = copy.deepcopy(current_val)
        if field_conflicts:
            conflicts.append({
                "widget_key": key, "kind": CONFLICT_FIELD,
                "reason": "双方修改了同一部件的相同字段且取值不同",
                "fields": field_conflicts,
            })
        else:
            merged[key] = combined
            decisions.append({"widget_key": key, "action": "update", "result": AUTO_MERGED})

    # 输出顺序：以 current 为主序，新增的 incoming 部件追加在末尾
    ordered: list[dict[str, Any]] = []
    for widget in current:
        if widget["widget_key"] in merged:
            ordered.append(merged.pop(widget["widget_key"]))
    ordered.extend(merged.values())
    return MergeOutcome(merged_widgets=ordered, decisions=decisions, conflicts=conflicts)


def _field_conflicts(left: dict[str, Any], right: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for field_name in ("title", "type", "position", "config"):
        if left.get(field_name) != right.get(field_name):
            out.append({
                "field": field_name,
                "current": left.get(field_name),
                "incoming": right.get(field_name),
            })
    return out
