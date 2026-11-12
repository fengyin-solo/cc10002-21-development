"""三向合并引擎的纯单元测试（不经过 HTTP）。

验证移动 vs 删除、字段级自动合并、双方删除、新增部件等裁决的可解释性。
运行：PYTHONPATH=/tmp/pydeps:/workspace/backend python3 -s tests/test_merge_unit.py
"""
from __future__ import annotations

from app.collab.errors import ConflictError
from app.collab.merge import three_way_merge


def w(key: str, title: str = "t", pos: tuple[int, int, int, int] = (0, 0, 1, 1)) -> dict:
    return {
        "widget_key": key,
        "title": title,
        "type": "line",
        "position": {"x": pos[0], "y": pos[1], "w": pos[2], "h": pos[3]},
        "config": {},
    }


def main() -> None:
    # 1. 一方移动、另一方删除同一部件 → 冲突，不产出该部件的合并结果
    base = [w("w1"), w("w2")]
    current = [w("w1"), {**w("w2"), "position": {"x": 5, "y": 0, "w": 1, "h": 1}}]
    incoming = [w("w1")]  # 删了 w2
    outcome = three_way_merge(base, current, incoming)
    assert outcome.has_conflict, "移动 vs 删除必须冲突"
    assert outcome.conflicts[0]["kind"] == "conflict_delete_update"
    assert outcome.conflicts[0]["widget_key"] == "w2"
    assert "w2" not in {x["widget_key"] for x in outcome.merged_widgets}

    # 2. 双方都删除 → 无冲突，保持删除
    outcome = three_way_merge(base, [w("w1")], [w("w1")])
    assert not outcome.has_conflict
    assert [x["widget_key"] for x in outcome.merged_widgets] == ["w1"]
    delete_decision = next(d for d in outcome.decisions if d["widget_key"] == "w2")
    assert delete_decision["result"] == "both_deleted"

    # 3. 双方改不同字段（标题 vs 位置）→ 自动合并，两边改动都保留
    current = [{**w("w1", "新标题")}]
    incoming = [{**w("w1", pos=(3, 3, 2, 2))}]
    outcome = three_way_merge([w("w1")], current, incoming)
    assert not outcome.has_conflict, outcome.conflicts
    merged = outcome.merged_widgets[0]
    assert merged["title"] == "新标题"
    assert merged["position"] == {"x": 3, "y": 3, "w": 2, "h": 2}
    assert outcome.decisions[0]["result"] == "auto_merged"

    # 4. 双方改同一字段且取值不同 → 字段级冲突，逐字段列出
    outcome = three_way_merge([w("w1", "原")], [w("w1", "甲")], [w("w1", "乙")])
    assert outcome.has_conflict
    assert outcome.conflicts[0]["kind"] == "conflict_field"
    assert outcome.conflicts[0]["fields"][0]["field"] == "title"
    assert outcome.conflicts[0]["fields"][0]["current"] == "甲"
    assert outcome.conflicts[0]["fields"][0]["incoming"] == "乙"

    # 5. 双方相同修改 → 视为一致，直接采纳，不报冲突
    outcome = three_way_merge([w("w1", "原")], [w("w1", "一致")], [w("w1", "一致")])
    assert not outcome.has_conflict
    assert outcome.merged_widgets[0]["title"] == "一致"

    # 6. 仅 incoming 新增部件 → 接受新部件
    outcome = three_way_merge(base, base, [w("w1"), w("w2"), w("w3", "新部件")])
    assert not outcome.has_conflict
    assert "w3" in {x["widget_key"] for x in outcome.merged_widgets}
    assert any(d.get("result") == "accepted_incoming_add" for d in outcome.decisions)

    # 7. 一方删除、另一方未动 → 接受删除
    outcome = three_way_merge(base, [w("w1")], base)
    assert not outcome.has_conflict
    assert [x["widget_key"] for x in outcome.merged_widgets] == ["w1"]

    # 8. 传入重复标识 → 直接拒绝
    try:
        three_way_merge([], [w("w1"), w("w1")], [])
        raise AssertionError("重复标识应当报错")
    except ConflictError:
        pass

    print("合并引擎单元测试全部通过 ✅（8 组场景）")


if __name__ == "__main__":
    main()
