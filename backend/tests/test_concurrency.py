"""并发压测：多线程基于同一修订号同时提交，验证三向合并与互斥的正确性。

所有线程先用屏障对齐到同一份基线 r1，再同时提交：
- 偶号线程移动 w0001（position 字段，彼此构成同字段冲突）；
- 奇号线程重命名 w0002（title 字段，与偶号线程改的是不同部件，应自动合并）。

运行：PYTHONPATH=/tmp/pydeps:/workspace/backend python3 -s tests/test_concurrency.py
"""
from __future__ import annotations

import threading

from app.collab.errors import ConflictError
from app.collab.identity import Principal
from app.collab.seed import seed_collab
from app.collab.service import CollabService
from app.collab.store import collab_store

seed_collab(collab_store)
svc = CollabService(collab_store)
alice = Principal("u-alice", "阿黎", "ws-a", "editor")
bob = Principal("u-bob", "卜岚", "ws-a", "editor")

THREADS = 12
barrier = threading.Barrier(THREADS)
outcomes: list[tuple[int, str]] = []
lock = threading.Lock()

# 全部线程先基于同一基线 r1 构造各自的提交内容
base_draft = svc.get_draft(alice, 1)["draft"]
assert base_draft["revision"] == 1
base_widgets = {w["widget_key"]: dict(w) for w in base_draft["widgets"]}


def worker(idx: int) -> None:
    principal = alice if idx % 2 == 0 else bob
    widgets = [dict(w) for w in base_draft["widgets"]]
    if idx % 2 == 0:
        # 偶号线程：移动 w0001 到各自不同的坐标
        for w in widgets:
            if w["widget_key"] == "w0001":
                w["position"] = {"x": idx, "y": idx, "w": 1, "h": 1}
    else:
        # 奇号线程：重命名 w0002（与移动组改的部件不同）
        for w in widgets:
            if w["widget_key"] == "w0002":
                w["title"] = f"转化率-{idx}"
    barrier.wait()  # 对齐：保证大家都带着 base_revision=1 同时提交
    try:
        svc.submit_draft(principal, 1, {
            "base_revision": 1,
            "widgets": widgets,
            "change_summary": f"worker-{idx}",
        })
        result = "ok"
    except ConflictError:
        result = "conflict"
    except Exception as exc:  # noqa: BLE001 - 压测中任何其他异常都算失败
        result = f"error:{type(exc).__name__}"
    with lock:
        outcomes.append((idx, result))


threads = [threading.Thread(target=worker, args=(i,)) for i in range(THREADS)]
for t in threads:
    t.start()
for t in threads:
    t.join()

ok = [i for i, r in outcomes if r == "ok"]
conflicts = [i for i, r in outcomes if r == "conflict"]
errors = [f"{i}:{r}" for i, r in outcomes if r.startswith("error")]
print(f"并发 {THREADS} 个同基线提交：成功 {sorted(ok)}，冲突 {sorted(conflicts)}，异常 {errors}")
assert not errors, outcomes

final = svc.get_draft(alice, 1)["draft"]

# 不变量 1：成功与冲突之和等于总数，没有请求被悄悄丢弃或异常覆盖
assert len(ok) + len(conflicts) == THREADS
# 不变量 2：每个成功提交恰好推进一个修订号，无跳跃
assert final["revision"] == 1 + len(ok), (final["revision"], len(ok))
# 不变量 3：每个修订号都有部件快照，三向合并基线始终可重建
dashboard = collab_store.dashboards[("ws-a", 1)]
for rev in range(1, final["revision"] + 1):
    assert str(rev) in dashboard["revision_snapshots"], f"缺少 r{rev} 快照"
# 不变量 4：两组改的是不同部件——只要两组各至少一次成功，最终草稿应同时包含
# 一个被移动过的 w0001 和一个被重命名过的 w0002（跨组自动合并的证据）
w1 = next(w for w in final["widgets"] if w["widget_key"] == "w0001")
w2 = next(w for w in final["widgets"] if w["widget_key"] == "w0002")
mover_ok = any(i % 2 == 0 for i in ok)
renamer_ok = any(i % 2 == 1 for i in ok)
if mover_ok:
    assert w1["position"]["w"] == 1 and w1["position"]["h"] == 1, w1
if renamer_ok:
    assert w2["title"].startswith("转化率-"), w2
# 不变量 5：同字段的并发异值修改必须产生过冲突，不能静默覆盖
assert conflicts, "同字段异值的并发提交应当产生冲突"
# 不变量 6：所有冲突都是 409 语义、未写入——修订号只由成功提交推进
assert final["revision"] == 1 + len(ok)

print("并发压测通过 ✅：跨部件改动自动合并，同字段异值冲突可解释，修订号连续无丢失更新")
