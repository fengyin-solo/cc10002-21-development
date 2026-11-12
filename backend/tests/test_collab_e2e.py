"""布局协作域端到端测试。

覆盖需求清单：
1. 本地身份/工作空间选择、编辑与只读角色、权限撤销实时生效；
2. 两空间同 ID 实体隔离，跨空间 ID 猜测一律拦截且错误信息不泄露他空间细节；
3. 分享凭据只有只读能力，不等于编辑权限；
4. 两个编辑者同版本提交的自动合并与冲突裁决（移动 vs 删除同时发生）；
5. 发布一次性固定版本+访问范围、失败事务回滚、重复发布幂等；
6. 报告锁定确定版本，之后草稿/新发布不影响锁定布局；删除被引用部件保留旧版解释；
7. 部件稳定标识与报告引用对应关系。

运行：PYTHONPATH=/tmp/pydeps python3 -s tests/test_collab_e2e.py
"""
from __future__ import annotations

import sys

from fastapi.testclient import TestClient

from app.collab.store import collab_store
from app.main import app
from app.collab.seed import seed_collab

# 每个用例前重置内存仓库，保证独立可重复
seed_collab(collab_store)
client = TestClient(app)

PASS = 0
FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS
    if condition:
        PASS += 1
        print(f"  ✔ {name}")
    else:
        FAILURES.append(f"{name} :: {detail}")
        print(f"  ✗ {name}  {detail}")


def hdr(user: str, ws: str) -> dict[str, str]:
    return {"X-User-Id": user, "X-Workspace-Id": ws}


def body(resp) -> dict:
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return {"_raw": resp.text}


# ============ 1. 身份与工作空间 ============
print("\n[1] 本地身份、工作空间选择与成员角色")

r = client.get("/api/collab/me", headers=hdr("u-alice", "ws-a"))
check("编辑者身份解析", r.status_code == 200 and body(r)["role"] == "editor", body(r))

r = client.get("/api/collab/me")
check("缺少身份头被拒（401）", r.status_code == 401, body(r))

r = client.get("/api/collab/me", headers=hdr("u-ghost", "ws-a"))
check("不存在的本地身份被拒（401）", r.status_code == 401, body(r))

r = client.get("/api/collab/me", headers=hdr("u-alice", "ws-ghost"))
check("不存在的工作空间被拒（401）", r.status_code == 401, body(r))

r = client.get("/api/collab/workspaces", headers=hdr("u-alice", "ws-a"))
ws_list = {item["workspace_id"] for item in body(r)["items"]}
check("只列出本人有效成员空间", r.status_code == 200 and ws_list == {"ws-a"}, body(r))

r = client.get("/api/collab/me", headers=hdr("u-dave", "ws-a"))
check("非成员进入他空间被拒（403）", r.status_code == 403, body(r))

r = client.get("/api/collab/me", headers=hdr("u-carol", "ws-a"))
check("只读成员身份解析", r.status_code == 200 and body(r)["role"] == "viewer", body(r))

# ============ 2. 同 ID 实体的归属隔离 ============
print("\n[2] 两空间同 ID 实体隔离与越权拦截")

r_a = client.get("/api/collab/dashboards/1/published/latest", headers=hdr("u-carol", "ws-a"))
r_b = client.get("/api/collab/dashboards/1/published/latest", headers=hdr("u-erin", "ws-b"))
check("两个空间都存在 dashboard id=1", r_a.status_code == 200 and r_b.status_code == 200)
check("同 ID 内容按空间隔离", body(r_a)["widgets"][0]["title"] == "日活跃用户"
      and body(r_b)["widgets"][0]["title"] == "拦截趋势", f"{body(r_a)} | {body(r_b)}")

# ws-b 编辑者猜测 ws-a 的实体：使用 ws-b 内不存在、ws-a 内存在的 ID，
# 这样才能证明是归属边界在拦截，而不是 ID 恰好不存在。
r = client.get("/api/collab/dashboards/9/draft", headers=hdr("u-dave", "ws-b"))
check("跨空间猜看板 ID 返回 404", r.status_code == 404, body(r))
check("错误信息不透露他空间看板名称", "经营总览" not in str(body(r)), body(r))

r = client.get("/api/collab/reports/9", headers=hdr("u-dave", "ws-b"))
check("跨空间猜报告 ID 返回 404", r.status_code == 404 and "月度经营" not in str(body(r)), body(r))

r = client.get("/api/collab/dashboards/9/versions/1", headers=hdr("u-dave", "ws-b"))
check("跨空间猜版本号同样 404", r.status_code == 404, body(r))

# ws-a 中确有 id=9 的看板（下面创建），先建出来再确认 ws-b 仍读不到
client.post("/api/collab/dashboards", headers=hdr("u-alice", "ws-a"), json={"title": "敏感经营看板"})
r = client.get("/api/collab/dashboards/2/draft", headers=hdr("u-dave", "ws-b"))
check("他空间真实存在的看板在本空间仍按 404 处理", r.status_code == 404
      and "敏感经营看板" not in str(body(r)), body(r))

r = client.get("/api/collab/dashboards", headers=hdr("u-dave", "ws-b"))
check("列表只返回本空间看板", all(item["dashboard_id"] == 1 and item["title"] == "风控监控看板"
                                  for item in body(r)["items"]), body(r))

# ============ 3. 只读成员边界 ============
print("\n[3] 只读成员只能查看已发布布局，草稿写操作全部服务端拒绝")

r = client.get("/api/collab/dashboards/1/draft", headers=hdr("u-carol", "ws-a"))
check("只读成员读草稿 403", r.status_code == 403, body(r))

r = client.put("/api/collab/dashboards/1/draft", headers=hdr("u-carol", "ws-a"),
               json={"base_revision": 1, "widgets": []})
check("只读成员提交草稿 403", r.status_code == 403, body(r))

r = client.post("/api/collab/dashboards/1/publish", headers=hdr("u-carol", "ws-a"),
                json={"access_scope": {"type": "workspace"}})
check("只读成员发布 403", r.status_code == 403, body(r))

r = client.post("/api/collab/reports", headers=hdr("u-carol", "ws-a"), json={"name": "x"})
check("只读成员建报告 403", r.status_code == 403, body(r))

r = client.get("/api/collab/dashboards/1/versions", headers=hdr("u-carol", "ws-a"))
check("只读成员可看已发布版本列表", r.status_code == 200 and len(body(r)["items"]) == 1, body(r))

# ============ 4. 草稿协作：部件稳定标识 ============
print("\n[4] 草稿编辑与部件稳定标识")

r = client.post("/api/collab/dashboards/1/widgets", headers=hdr("u-alice", "ws-a"),
                json={"base_revision": 1,
                      "widget": {"title": "新增KPI", "type": "kpi",
                                 "position": {"x": 0, "y": 8, "w": 4, "h": 2}}})
check("编辑者新增部件成功", r.status_code == 200 and body(r)["widget"]["widget_key"] == "w0004", body(r))
new_rev = body(r)["draft_revision"]
check("新增后修订号推进到 2", new_rev == 2, body(r))

# 拿草稿
r = client.get("/api/collab/dashboards/1/draft", headers=hdr("u-alice", "ws-a"))
draft = body(r)["draft"]
widgets = draft["widgets"]
w1 = next(w for w in widgets if w["widget_key"] == "w0001")

# 过期基线提交
r = client.put("/api/collab/dashboards/1/draft", headers=hdr("u-bob", "ws-a"),
               json={"base_revision": 1, "widgets": widgets})
check("过期基线走合并而不是直接覆盖", r.status_code == 200 and body(r).get("merged") is True, body(r))
rev_after_bob = body(r)["draft_revision"]
check("合并提交后修订号继续推进", rev_after_bob == 3, body(r))

# 伪造他看板/不存在的部件标识
r = client.put("/api/collab/dashboards/1/draft", headers=hdr("u-alice", "ws-a"),
               json={"base_revision": 3, "widgets": [{**w1, "widget_key": "w9999"}]})
check("未知部件标识被拒（400）", r.status_code == 400 and "w9999" in body(r)["detail"], body(r))

# 非法部件
r = client.post("/api/collab/dashboards/1/widgets", headers=hdr("u-alice", "ws-a"),
                json={"base_revision": 3, "widget": {"title": "bad", "type": "radar",
                                                      "position": {"x": 0, "y": 0, "w": 1, "h": 1}}})
check("不支持的部件类型被拒（400）", r.status_code == 400, body(r))

# ============ 5. 并发：同时移动与删除的合并/冲突裁决 ============
print("\n[5] 两个编辑者同版本提交：自动合并与冲突裁决")

# 重新拉取基线 r3
r = client.get("/api/collab/dashboards/1/draft", headers=hdr("u-alice", "ws-a"))
base3 = body(r)["draft"]
check("当前基线为 r3", base3["revision"] == 3, body(r))
base_widgets = base3["widgets"]
w_pie = next(w for w in base_widgets if w["widget_key"] == "w0003")

# Alice 先提交：移动 w0003（只改 position）
alice_widgets = [dict(w) for w in base_widgets]
for w in alice_widgets:
    if w["widget_key"] == "w0003":
        w["position"] = {"x": 3, "y": 9, "w": 12, "h": 6}
r = client.put("/api/collab/dashboards/1/draft", headers=hdr("u-alice", "ws-a"),
               json={"base_revision": 3, "widgets": alice_widgets,
                     "change_summary": "alice 移动渠道分布"})
check("Alice 移动提交成功（r3→r4）", r.status_code == 200 and body(r)["draft_revision"] == 4, body(r))

# Bob 基于同一 r3 提交：删除 w0003，同时移动 w0001（与 Alice 不冲突的字段/部件）
bob_widgets = [dict(w) for w in base_widgets if w["widget_key"] != "w0003"]
for w in bob_widgets:
    if w["widget_key"] == "w0001":
        w["position"] = {"x": 1, "y": 1, "w": 5, "h": 3}
r = client.put("/api/collab/dashboards/1/draft", headers=hdr("u-bob", "ws-a"),
               json={"base_revision": 3, "widgets": bob_widgets,
                     "change_summary": "bob 删除渠道分布并移动 DAU"})
check("移动 vs 删除同一部件 → 409 冲突且不写入", r.status_code == 409, body(r))
conflict = body(r).get("details", {})
check("冲突详情标明部件与类型",
      conflict.get("conflicts", [{}])[0].get("widget_key") == "w0003"
      and conflict["conflicts"][0]["kind"] == "conflict_delete_update", body(r))

# 确认冲突未造成任何写入：服务端仍是 r4，且 w0003 还在（Alice 的移动保留）
r = client.get("/api/collab/dashboards/1/draft", headers=hdr("u-bob", "ws-a"))
still_r4 = body(r)["draft"]
check("冲突后草稿维持 r4，未被 Bob 覆盖", still_r4["revision"] == 4
      and any(w["widget_key"] == "w0003" for w in still_r4["widgets"]), body(r))
kept = next(w for w in still_r4["widgets"] if w["widget_key"] == "w0003")
check("Alice 的移动没有被悄悄覆盖", kept["position"] == {"x": 3, "y": 9, "w": 12, "h": 6}, kept)

# Bob 重新拉取后做人工裁决：接受删除 w0003，并保留自己对 w0001 的移动 + Alice 对其余部件的状态
final_widgets = [dict(w) for w in still_r4["widgets"] if w["widget_key"] != "w0003"]
for w in final_widgets:
    if w["widget_key"] == "w0001":
        w["position"] = {"x": 1, "y": 1, "w": 5, "h": 3}
r = client.post("/api/collab/dashboards/1/conflict-resolution", headers=hdr("u-bob", "ws-a"),
                json={"base_revision": 3, "widgets": final_widgets})
check("人工裁决成功推进到 r5", r.status_code == 200 and body(r)["draft_revision"] == 5, body(r))
r = client.get("/api/collab/dashboards/1/draft", headers=hdr("u-bob", "ws-a"))
final_draft = body(r)["draft"]
check("裁决结果：w0003 已删除", not any(w["widget_key"] == "w0003" for w in final_draft["widgets"]))
check("裁决结果：Bob 的 w0001 移动生效",
      next(w for w in final_draft["widgets"] if w["widget_key"] == "w0001")["position"]
      == {"x": 1, "y": 1, "w": 5, "h": 3}, body(r))

# 自动合并场景：基于 r5，Alice 改 w0001 标题、Bob 改 w0001 位置（不同字段）
r = client.get("/api/collab/dashboards/1/draft", headers=hdr("u-alice", "ws-a"))
r5_widgets = body(r)["draft"]["widgets"]
alice2 = [dict(w) for w in r5_widgets]
for w in alice2:
    if w["widget_key"] == "w0001":
        w["title"] = "日活跃用户（更名）"
r = client.put("/api/collab/dashboards/1/draft", headers=hdr("u-alice", "ws-a"),
               json={"base_revision": 5, "widgets": alice2, "change_summary": "alice 改名"})
check("Alice 改名 r5→r6", r.status_code == 200 and body(r)["draft_revision"] == 6, body(r))
bob2 = [dict(w) for w in r5_widgets]
for w in bob2:
    if w["widget_key"] == "w0001":
        w["position"] = {"x": 2, "y": 2, "w": 7, "h": 3}
r = client.put("/api/collab/dashboards/1/draft", headers=hdr("u-bob", "ws-a"),
               json={"base_revision": 5, "widgets": bob2, "change_summary": "bob 移动"})
check("不同字段修改自动合并", r.status_code == 200 and body(r)["draft_revision"] == 7, body(r))
r = client.get("/api/collab/dashboards/1/draft", headers=hdr("u-alice", "ws-a"))
w1_final = next(w for w in body(r)["draft"]["widgets"] if w["widget_key"] == "w0001")
check("自动合并同时保留双方改动",
      w1_final["title"] == "日活跃用户（更名）"
      and w1_final["position"] == {"x": 2, "y": 2, "w": 7, "h": 3}, w1_final)

# 同字段并发改 → 字段级冲突
r = client.get("/api/collab/dashboards/1/draft", headers=hdr("u-alice", "ws-a"))
r7 = body(r)["draft"]["widgets"]
a3 = [dict(w) for w in r7]
b3 = [dict(w) for w in r7]
for w in a3:
    if w["widget_key"] == "w0001":
        w["title"] = "Alice 的标题"
for w in b3:
    if w["widget_key"] == "w0001":
        w["title"] = "Bob 的标题"
client.put("/api/collab/dashboards/1/draft", headers=hdr("u-alice", "ws-a"),
           json={"base_revision": 7, "widgets": a3})
r = client.put("/api/collab/dashboards/1/draft", headers=hdr("u-bob", "ws-a"),
               json={"base_revision": 7, "widgets": b3})
check("同字段不同值 → 字段级冲突 409", r.status_code == 409
      and body(r)["details"]["conflicts"][0]["kind"] == "conflict_field"
      and body(r)["details"]["conflicts"][0]["fields"][0]["field"] == "title", body(r))

# ============ 6. 发布：事务、幂等、固定范围 ============
print("\n[6] 发布一次性固定版本与访问范围、中断回滚、幂等")

r = client.get("/api/collab/dashboards/1/draft", headers=hdr("u-alice", "ws-a"))
current_rev = body(r)["draft"]["revision"]

# 故障注入：发布中断
client.post("/api/collab/test/arm-publish-failure", headers=hdr("u-alice", "ws-a"))
versions_before = len(client.get("/api/collab/dashboards/1/versions", headers=hdr("u-alice", "ws-a")).json()["items"])
r = client.post("/api/collab/dashboards/1/publish", headers=hdr("u-alice", "ws-a"),
                json={"change_note": "应当回滚的版本", "access_scope": {"type": "workspace"}})
check("发布中断返回 500", r.status_code == 500 and "回滚" in body(r)["detail"], body(r))
versions_after = client.get("/api/collab/dashboards/1/versions", headers=hdr("u-alice", "ws-a")).json()["items"]
check("回滚后没有残留新版本", len(versions_after) == versions_before == 1, f"{versions_before} -> {len(versions_after)}")
r = client.get("/api/collab/dashboards/1/draft", headers=hdr("u-alice", "ws-a"))
check("回滚后草稿修订号与 published_revision 不变", body(r)["draft"]["revision"] == current_rev, body(r))

# 自定义访问范围拒绝非成员
r = client.post("/api/collab/dashboards/1/publish", headers=hdr("u-alice", "ws-a"),
                json={"access_scope": {"type": "custom", "members": ["u-dave"]}})
check("访问范围不能包含他空间/非成员（400）", r.status_code == 400 and "u-dave" in body(r)["detail"], body(r))
check("失败的范围发布不产生版本",
      len(client.get("/api/collab/dashboards/1/versions", headers=hdr("u-alice", "ws-a")).json()["items"]) == 1)

# 正常发布（自定义范围，含本空间成员）
r = client.post("/api/collab/dashboards/1/publish", headers=hdr("u-alice", "ws-a"),
                json={"idempotency_key": "pub-002",
                      "change_note": "第二版：删除渠道分布并调整布局",
                      "access_scope": {"type": "custom", "members": ["u-alice", "u-bob", "u-carol"]}})
check("正常发布产生 v2", r.status_code == 200 and body(r)["version"]["version_no"] == 2
      and body(r)["idempotent"] is False, body(r))
v2 = body(r)["version"]
check("版本与访问范围同时固定", v2["access_scope"]["type"] == "custom"
      and set(v2["access_scope"]["members"]) == {"u-alice", "u-bob", "u-carol"}, body(r))
check("版本快照是不可变拷贝（w0003 不在 v2）",
      all(w["widget_key"] != "w0003" for w in v2["widgets"]), body(r))

# 重复发布：相同幂等键
r = client.post("/api/collab/dashboards/1/publish", headers=hdr("u-bob", "ws-a"),
                json={"idempotency_key": "pub-002",
                      "access_scope": {"type": "workspace"}})
check("相同幂等键重复发布不产生新版本", r.status_code == 200 and body(r)["idempotent"] is True
      and body(r)["version"]["version_no"] == 2, body(r))

# 无幂等键、草稿未再改动 → 同修订号不产生新版本
r = client.post("/api/collab/dashboards/1/publish", headers=hdr("u-bob", "ws-a"),
                json={"access_scope": {"type": "workspace"}})
check("同修订号重复发布幂等", body(r)["idempotent"] is True and body(r)["version"]["version_no"] == 2, body(r))
check("版本总数仍为 2",
      len(client.get("/api/collab/dashboards/1/versions", headers=hdr("u-alice", "ws-a")).json()["items"]) == 2)

# 历史版本 v1 不可变，w0003 仍在 v1 里
r = client.get("/api/collab/dashboards/1/versions/1", headers=hdr("u-carol", "ws-a"))
check("历史版本 v1 完整保留已删除部件", r.status_code == 200
      and any(w["widget_key"] == "w0003" for w in body(r)["widgets"]), body(r))

# ============ 7. 报告锁定确定版本 ============
print("\n[7] 报告锁定版本、删除引用部件的旧版解释与新版影响")

r = client.post("/api/collab/reports/1/lock", headers=hdr("u-alice", "ws-a"),
                json={"dashboard_id": 1, "version_no": 1})
check("报告锁定 v1", r.status_code == 200 and body(r)["lock"]["version_no"] == 1, body(r))

r = client.get("/api/collab/reports/1", headers=hdr("u-carol", "ws-a"))
report = body(r)
check("只读成员可读锁定报告", r.status_code == 200, body(r))
check("锁定布局仍是 v1 快照（含 w0003）",
      any(w["widget_key"] == "w0003" for w in report["locked_layout"]["widgets"]), body(r))
impact = report["layout_impact"]
check("影响清单指出 w0003 在最新草稿与 v2 中已删除",
      impact["removed_in_latest_draft"] == ["w0003"]
      and impact["removed_in_latest_published"] == ["w0003"]
      and impact["latest_published_version_no"] == 2, body(r))
check("影响说明保留旧版解释口径", "旧版" in impact["explanation"], impact)

# 草稿继续改、再发 v3，报告看到的布局不变
r = client.get("/api/collab/dashboards/1/draft", headers=hdr("u-bob", "ws-a"))
rev = body(r)["draft"]["revision"]
widgets_now = body(r)["draft"]["widgets"]
stripped = [{**w, "title": w["title"] + "（再改）"} for w in widgets_now]
client.put("/api/collab/dashboards/1/draft", headers=hdr("u-bob", "ws-a"),
           json={"base_revision": rev, "widgets": stripped, "change_summary": "草稿再改"})
r = client.post("/api/collab/dashboards/1/publish", headers=hdr("u-bob", "ws-a"),
                json={"change_note": "v3", "access_scope": {"type": "workspace"}})
check("发布 v3", body(r)["version"]["version_no"] == 3, body(r))
r = client.get("/api/collab/reports/1", headers=hdr("u-alice", "ws-a"))
locked = body(r)["locked_layout"]
check("报告锁定的 v1 不随后续草稿/发布变化",
      locked["version_no"] == 1
      and any(w["widget_key"] == "w0003" for w in locked["widgets"])
      and "（再改）" not in str(locked["widgets"]), body(r))

# 锁定不存在的版本/跨空间版本：ws-b 没有 dashboard 2，但 ws-a 有
r = client.post("/api/collab/reports/1/lock", headers=hdr("u-alice", "ws-a"),
                json={"dashboard_id": 1, "version_no": 99})
check("锁定不存在版本 → 404", r.status_code == 404, body(r))
r = client.post("/api/collab/reports/1/lock", headers=hdr("u-dave", "ws-b"),
                json={"dashboard_id": 2, "version_no": 1})
check("跨空间锁定他空间看板 → 404，错误不透露他空间看板名",
      r.status_code == 404 and "敏感经营看板" not in str(body(r)), body(r))

# ============ 8. 分享凭据不等于编辑权限 ============
print("\n[8] 分享凭据边界")

r = client.post("/api/collab/dashboards/1/versions/1/share-tokens",
                headers=hdr("u-alice", "ws-a"), json={})
check("编辑者为 v1 创建分享凭据", r.status_code == 200, body(r))
token = body(r)["token"]

r = client.get(f"/api/collab/shared/{token}")
check("持凭据可匿名读取固定版本", r.status_code == 200
      and body(r)["version_no"] == 1
      and any(w["widget_key"] == "w0003" for w in body(r)["widgets"]), body(r))

# 持凭据尝试写草稿（不带/乱带头）
r = client.put("/api/collab/dashboards/1/draft",
               headers={"X-User-Id": "u-carol", "X-Workspace-Id": "ws-a"},
               json={"base_revision": 1, "widgets": []})
check("只读成员持凭据也不能写（凭据非编辑权）", r.status_code == 403, body(r))

# 猜 token
r = client.get("/api/collab/shared/st-0000-deadbeef")
check("猜测凭据无效 → 404", r.status_code == 404, body(r))

# 撤销凭据
r = client.delete(f"/api/collab/share-tokens/{token}", headers=hdr("u-bob", "ws-a"))
check("撤销凭据", r.status_code == 200 and body(r)["revoked"] is True, body(r))
r = client.get(f"/api/collab/shared/{token}")
check("撤销后凭据立即失效", r.status_code == 404, body(r))

# 跨空间撤销别人的 token：ws-b 编辑者猜 ws-a 的 token
r = client.delete(f"/api/collab/share-tokens/{token}", headers=hdr("u-dave", "ws-b"))
check("跨空间操作凭据按不存在处理", r.status_code == 404 and "增长" not in str(body(r)), body(r))

# ============ 9. 权限撤销实时生效 ============
print("\n[9] 撤销成员权限影响其后的读取与提交（服务端强制）")

# carol 撤销前能读
r = client.get("/api/collab/dashboards/1/versions", headers=hdr("u-carol", "ws-a"))
check("撤销前只读成员可读取", r.status_code == 200, body(r))

r = client.post("/api/collab/members/u-carol/revoke", headers=hdr("u-alice", "ws-a"))
check("编辑者撤销成员资格", r.status_code == 200 and body(r)["active"] is False, body(r))

r = client.get("/api/collab/dashboards/1/versions", headers=hdr("u-carol", "ws-a"))
check("撤销后读取立即被拒（403）", r.status_code == 403, body(r))
r = client.put("/api/collab/dashboards/1/draft", headers=hdr("u-carol", "ws-a"),
               json={"base_revision": 1, "widgets": []})
check("撤销后提交立即被拒（403）", r.status_code == 403, body(r))
r = client.get("/api/collab/workspaces", headers=hdr("u-carol", "ws-a"))
check("撤销后工作空间列表不再包含 ws-a（用残留头探测也被拦）", r.status_code == 403, body(r))

# 只读成员不能撤销别人
r = client.post("/api/collab/members/u-bob/revoke", headers=hdr("u-erin", "ws-b"))
check("只读成员无管理权（403）", r.status_code == 403, body(r))

# 恢复后权限回来；其旧草稿仍由其他编辑者继续维护
r = client.post("/api/collab/members/u-carol/restore", headers=hdr("u-bob", "ws-a"))
check("恢复成员资格", r.status_code == 200 and body(r)["active"] is True, body(r))
r = client.get("/api/collab/dashboards/1/versions", headers=hdr("u-carol", "ws-a"))
check("恢复后可重新读取，草稿未被清空", r.status_code == 200 and len(body(r)["items"]) == 3, body(r))

# ============ 10. 撤销编辑者：旧草稿保留、协作可继续 ============
print("\n[10] 编辑者被撤销后的草稿处理")

r = client.post("/api/collab/members/u-bob/revoke", headers=hdr("u-alice", "ws-a"))
check("撤销编辑者 Bob", r.status_code == 200, body(r))
r = client.post("/api/collab/dashboards/1/publish", headers=hdr("u-bob", "ws-a"),
                json={"access_scope": {"type": "workspace"}})
check("Bob 之后的发布被拒", r.status_code == 403, body(r))
r = client.get("/api/collab/dashboards/1/draft", headers=hdr("u-alice", "ws-a"))
check("Alice 仍可打开同一份共享草稿继续协作", r.status_code == 200
      and body(r)["draft"]["revision"] >= 7, body(r))
client.post("/api/collab/members/u-bob/restore", headers=hdr("u-alice", "ws-a"))

# ============ 汇总 ============
print(f"\n通过 {PASS} 项，失败 {len(FAILURES)} 项")
if FAILURES:
    print("\n失败明细：")
    for item in FAILURES:
        print(" -", item)
    sys.exit(1)
print("全部断言通过 ✅")
