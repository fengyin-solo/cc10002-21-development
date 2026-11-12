/**
 * 布局协作管理页：本地身份/工作空间选择、成员管理、草稿协作与冲突裁决、
 * 版本发布、分享凭据与报告版本锁定。
 *
 * 所有按钮的显隐只是体验优化；服务端对每个写接口独立鉴权，
 * 越权调用会拿到 401/403/404，页面原样展示服务端裁决结果。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  collabApi,
  type CollabApiError,
  type DashboardSummary,
  type DraftState,
  type ReportDetail,
  type ReportSummary,
  type VersionSummary,
  type Widget,
} from '@/collab/api'
import { useCollabSession } from '@/collab/session'

const DEMO_USERS = [
  { user_id: 'u-alice', label: '阿黎（ws-a 编辑）' },
  { user_id: 'u-bob', label: '卜岚（ws-a 编辑）' },
  { user_id: 'u-carol', label: '卡罗（ws-a 只读）' },
  { user_id: 'u-dave', label: '戴维（ws-b 编辑）' },
  { user_id: 'u-erin', label: '伊琳（ws-b 只读）' },
]

const TABS = [
  { key: 'dashboards', label: '看板与草稿' },
  { key: 'versions', label: '已发布版本' },
  { key: 'reports', label: '报告引用' },
  { key: 'members', label: '成员与权限' },
] as const
type TabKey = (typeof TABS)[number]['key']

interface Me {
  user_id: string
  display_name: string
  workspace_id: string
  role: string
}

interface WorkspaceOption {
  workspace_id: string
  name: string
  role: string
}

interface Member {
  user_id: string
  display_name: string
  role: string
  active: boolean
}

function errorText(error: unknown): string {
  if (error instanceof Error) return error.message
  return '操作失败'
}

export default function CollabView() {
  const [session, setSession] = useCollabSession()
  const [me, setMe] = useState<Me | null>(null)
  const [workspaces, setWorkspaces] = useState<WorkspaceOption[]>([])
  const [tab, setTab] = useState<TabKey>('dashboards')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  const refreshIdentity = useCallback(async () => {
    setError('')
    try {
      const [meResp, wsResp] = await Promise.all([
        collabApi.me(session),
        collabApi.workspaces(session),
      ])
      setMe(meResp as Me)
      setWorkspaces(wsResp.items)
    } catch (err) {
      setMe(null)
      setWorkspaces([])
      setError(errorText(err))
    }
  }, [session])

  useEffect(() => {
    void refreshIdentity()
  }, [refreshIdentity])

  const isEditor = me?.role === 'editor'

  return (
    <section className="page" data-module="collab">
      <header className="page-head">
        <div>
          <h2>布局协作与版本发布</h2>
          <p className="page-desc">
            本地身份 + 工作空间归属隔离：编辑者维护共享草稿并发布不可变版本，只读成员只看已发布布局，
            报告锁定确定版本，跨空间访问由服务端拦截。
          </p>
        </div>
      </header>

      <div className="stat-card" style={{ marginBottom: 12 }}>
        <div className="filter-bar" style={{ marginBottom: 0 }}>
          <label className="filter-item">
            <span>本地身份（不接外部身份服务）</span>
            <select
              value={session.userId}
              onChange={(e) => setSession({ ...session, userId: e.target.value })}
            >
              {DEMO_USERS.map((u) => (
                <option key={u.user_id} value={u.user_id}>
                  {u.label}
                </option>
              ))}
            </select>
          </label>
          <label className="filter-item">
            <span>工作空间</span>
            <select
              value={session.workspaceId}
              onChange={(e) => setSession({ ...session, workspaceId: e.target.value })}
            >
              <option value="ws-a">ws-a 增长分析空间</option>
              <option value="ws-b">ws-b 风控分析空间</option>
            </select>
          </label>
          <div className="filter-item">
            <span>当前会话</span>
            <strong>
              {me ? `${me.display_name} · 角色：${me.role === 'editor' ? '编辑者' : '只读成员'}` : '未通过服务端鉴权'}
            </strong>
          </div>
          <div className="filter-item">
            <span>可进入的空间</span>
            <span>{workspaces.map((w) => `${w.name}（${w.role}）`).join('、') || '无'}</span>
          </div>
        </div>
      </div>

      <nav className="filter-bar">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            className={`btn ${tab === t.key ? 'primary' : ''}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {notice && <p className="page-foot" style={{ color: '#067647' }}>{notice}</p>}
      {error && <p className="error-text">{error}</p>}

      {tab === 'dashboards' && (
        <DashboardTab
          session={session}
          isEditor={isEditor}
          onNotice={setNotice}
          onError={setError}
        />
      )}
      {tab === 'versions' && <VersionsTab session={session} onNotice={setNotice} onError={setError} />}
      {tab === 'reports' && <ReportsTab session={session} isEditor={isEditor} onNotice={setNotice} onError={setError} />}
      {tab === 'members' && <MembersTab session={session} isEditor={isEditor} onNotice={setNotice} onError={setError} />}
    </section>
  )
}

/* ---------------- 看板与草稿 ---------------- */

function DashboardTab({
  session,
  isEditor,
  onNotice,
  onError,
}: {
  session: ReturnType<typeof useCollabSession>[0]
  isEditor: boolean
  onNotice: (m: string) => void
  onError: (m: string) => void
}) {
  const [dashboards, setDashboards] = useState<DashboardSummary[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [draft, setDraft] = useState<DraftState | null>(null)
  const [baseRevision, setBaseRevision] = useState(0)
  const [conflict, setConflict] = useState<CollabApiError | null>(null)

  const load = useCallback(async () => {
    onError('')
    try {
      const resp = await collabApi.dashboards(session)
      setDashboards(resp.items)
      if (resp.items.length && selected === null) setSelected(resp.items[0].dashboard_id)
    } catch (err) {
      onError(errorText(err))
    }
  }, [session, selected, onError])

  const loadDraft = useCallback(
    async (id: number) => {
      onError('')
      setConflict(null)
      try {
        const resp = await collabApi.draft(session, id)
        setDraft(resp.draft)
        setBaseRevision(resp.draft.revision)
      } catch (err) {
        setDraft(null)
        onError(errorText(err))
      }
    },
    [session, onError],
  )

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (selected !== null && isEditor) void loadDraft(selected)
    else setDraft(null)
  }, [selected, isEditor, loadDraft])

  const localWidgets = useMemo(() => draft?.widgets ?? [], [draft])

  function moveWidget(key: string, dx: number, dy: number) {
    if (!draft) return
    setDraft({
      ...draft,
      widgets: draft.widgets.map((w) =>
        w.widget_key === key
          ? { ...w, position: { ...w.position, x: Math.max(0, w.position.x + dx), y: Math.max(0, w.position.y + dy) } }
          : w,
      ),
    })
  }

  function removeWidget(key: string) {
    if (!draft) return
    setDraft({ ...draft, widgets: draft.widgets.filter((w) => w.widget_key !== key) })
  }

  async function submit(summary: string) {
    if (selected === null || !draft) return
    onError('')
    setConflict(null)
    try {
      const result = await collabApi.submitDraft(session, selected, {
        base_revision: baseRevision,
        widgets: draft.widgets,
        change_summary: summary,
      })
      onNotice(`草稿已提交（r${result.draft_revision}），合并裁决：${result.decisions.map((d) => d.result).join('、') || '无'}`)
      await loadDraft(selected)
      await load()
    } catch (err) {
      const apiError = err as CollabApiError
      if (apiError.status === 409) {
        setConflict(apiError)
        onError(`合并冲突，服务端未写入任何内容：${apiError.message}`)
      } else {
        onError(errorText(err))
      }
    }
  }

  async function resolveWithCurrent() {
    if (selected === null || !draft || !conflict) return
    try {
      await collabApi.resolveConflict(session, selected, {
        // 用冲突详情里记录的过期基线号，提交当前编辑区的最终部件表
        base_revision: (conflict.details as { base_revision: number }).base_revision,
        widgets: draft.widgets,
      })
      onNotice('冲突已按当前编辑区内容人工裁决并提交')
      setConflict(null)
      await loadDraft(selected)
      await load()
    } catch (err) {
      onError(errorText(err))
    }
  }

  async function publish() {
    if (selected === null) return
    onError('')
    try {
      const result = await collabApi.publish(session, selected, {
        idempotency_key: `ui-${selected}-${Date.now()}`,
        change_note: `由界面对 r${baseRevision} 发布`,
        access_scope: { type: 'workspace' },
      })
      onNotice(
        result.idempotent
          ? `重复发布已幂等处理，仍为版本 v${result.version.version_no}（${result.reason ?? '相同幂等键/修订号'}）`
          : `已发布新版本 v${result.version.version_no}，版本内容与访问范围一次性固定`,
      )
      await load()
    } catch (err) {
      onError(errorText(err))
    }
  }

  return (
    <div>
      <table className="data-table">
        <thead>
          <tr>
            <th>看板 ID</th>
            <th>名称</th>
            <th>草稿修订号</th>
            <th>已发布版本数</th>
            <th>最近编辑</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {dashboards.map((d) => (
            <tr key={d.dashboard_id}>
              <td>{d.dashboard_id}</td>
              <td>{d.title}</td>
              <td>r{d.draft_revision}</td>
              <td>{d.published_versions}</td>
              <td>{d.last_updated_by} · {d.last_updated_at}</td>
              <td className="row-actions">
                <button type="button" className="link" onClick={() => setSelected(d.dashboard_id)}>
                  {isEditor ? '编辑草稿' : '查看（只读成员无草稿权限）'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {!isEditor && (
        <p className="page-foot">
          只读成员不能读取草稿或发布；服务端会拒绝任何写请求，按钮缺失不构成安全边界。
        </p>
      )}

      {isEditor && selected !== null && draft && (
        <div className="stat-card" style={{ marginTop: 12 }}>
          <h3>看板 {selected} 草稿（编辑基线 r{baseRevision}，服务端最新 r{draft.revision}）</h3>
          <p className="page-desc">
            最近变更：{draft.last_change_summary}（{draft.updated_by} @ {draft.updated_at}）
          </p>
          <table className="data-table">
            <thead>
              <tr>
                <th>部件稳定标识</th>
                <th>标题</th>
                <th>类型</th>
                <th>位置 (x,y,w,h)</th>
                <th>移动</th>
                <th>删除</th>
              </tr>
            </thead>
            <tbody>
              {localWidgets.map((w: Widget) => (
                <tr key={w.widget_key}>
                  <td>{w.widget_key}</td>
                  <td>{w.title}</td>
                  <td>{w.type}</td>
                  <td>{`${w.position.x},${w.position.y},${w.position.w},${w.position.h}`}</td>
                  <td className="row-actions">
                    <button type="button" className="link" onClick={() => moveWidget(w.widget_key, -1, 0)}>←</button>
                    <button type="button" className="link" onClick={() => moveWidget(w.widget_key, 1, 0)}>→</button>
                    <button type="button" className="link" onClick={() => moveWidget(w.widget_key, 0, -1)}>↑</button>
                    <button type="button" className="link" onClick={() => moveWidget(w.widget_key, 0, 1)}>↓</button>
                  </td>
                  <td>
                    <button type="button" className="link" onClick={() => removeWidget(w.widget_key)}>
                      删除
                    </button>
                  </td>
                </tr>
              ))}
              {localWidgets.length === 0 && (
                <tr><td className="empty-state" colSpan={6}>草稿已无部件</td></tr>
              )}
            </tbody>
          </table>
          <div className="row-actions" style={{ marginTop: 10 }}>
            <button type="button" className="btn primary" onClick={() => void submit('界面编辑提交')}>
              提交草稿（带基线修订号）
            </button>
            <button type="button" className="btn" onClick={() => void publish()}>
              发布新版本（固定布局与访问范围）
            </button>
            <button type="button" className="btn ghost" onClick={() => void loadDraft(selected)}>
              重新拉取服务端草稿
            </button>
            {conflict && (
              <button type="button" className="btn primary" onClick={() => void resolveWithCurrent()}>
                按当前编辑区裁决冲突
              </button>
            )}
          </div>
          {conflict && (
            <pre className="stat-card" style={{ marginTop: 10, whiteSpace: 'pre-wrap' }}>
              {JSON.stringify((conflict as CollabApiError).details, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

/* ---------------- 已发布版本 ---------------- */

function VersionsTab({
  session,
  onNotice,
  onError,
}: {
  session: ReturnType<typeof useCollabSession>[0]
  onNotice: (m: string) => void
  onError: (m: string) => void
}) {
  const [dashboards, setDashboards] = useState<DashboardSummary[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [versions, setVersions] = useState<VersionSummary[]>([])

  const load = useCallback(async () => {
    try {
      const resp = await collabApi.dashboards(session)
      setDashboards(resp.items)
      if (selected === null && resp.items.length) setSelected(resp.items[0].dashboard_id)
    } catch (err) {
      onError(errorText(err))
    }
  }, [session, selected, onError])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (selected === null) return
    collabApi
      .versions(session, selected)
      .then((resp) => setVersions(resp.items))
      .catch((err) => onError(errorText(err)))
  }, [session, selected, onError])

  async function share(versionNo: number) {
    if (selected === null) return
    try {
      const resp = await collabApi.createShareToken(session, selected, versionNo)
      onNotice(`分享凭据（仅只读 v${versionNo}，不含编辑权）：${resp.token}`)
    } catch (err) {
      onError(errorText(err))
    }
  }

  return (
    <div>
      <label className="filter-item">
        <span>选择看板</span>
        <select value={selected ?? ''} onChange={(e) => setSelected(Number(e.target.value))}>
          {dashboards.map((d) => (
            <option key={d.dashboard_id} value={d.dashboard_id}>
              {d.dashboard_id} - {d.title}
            </option>
          ))}
        </select>
      </label>
      <table className="data-table" style={{ marginTop: 10 }}>
        <thead>
          <tr>
            <th>版本</th>
            <th>来源草稿修订号</th>
            <th>部件数</th>
            <th>部件标识</th>
            <th>访问范围</th>
            <th>发布人/时间</th>
            <th>分享</th>
          </tr>
        </thead>
        <tbody>
          {versions.map((v) => (
            <tr key={v.version_no}>
              <td>v{v.version_no}</td>
              <td>r{v.revision}</td>
              <td>{v.widget_count}</td>
              <td>{v.widget_keys.join(', ')}</td>
              <td>
                {v.access_scope.type === 'workspace'
                  ? `本空间（${v.access_scope.workspace_id}）`
                  : `自定义成员：${(v.access_scope.members ?? []).join('、')}`}
              </td>
              <td>{v.published_by} @ {v.published_at}</td>
              <td>
                <button type="button" className="link" onClick={() => void share(v.version_no)}>
                  生成只读凭据
                </button>
              </td>
            </tr>
          ))}
          {versions.length === 0 && (
            <tr><td className="empty-state" colSpan={7}>暂无已发布版本</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

/* ---------------- 报告引用 ---------------- */

function ReportsTab({
  session,
  isEditor,
  onNotice,
  onError,
}: {
  session: ReturnType<typeof useCollabSession>[0]
  isEditor: boolean
  onNotice: (m: string) => void
  onError: (m: string) => void
}) {
  const [reports, setReports] = useState<ReportSummary[]>([])
  const [dashboards, setDashboards] = useState<DashboardSummary[]>([])
  const [selectedReport, setSelectedReport] = useState<number | null>(null)
  const [detail, setDetail] = useState<ReportDetail | null>(null)
  const [lockDashboard, setLockDashboard] = useState<number>(1)
  const [lockVersion, setLockVersion] = useState<number>(1)

  const load = useCallback(async () => {
    try {
      const [r, d] = await Promise.all([collabApi.reports(session), collabApi.dashboards(session)])
      setReports(r.items)
      setDashboards(d.items)
    } catch (err) {
      onError(errorText(err))
    }
  }, [session, onError])

  useEffect(() => {
    void load()
  }, [load])

  async function openReport(id: number) {
    setSelectedReport(id)
    try {
      setDetail(await collabApi.report(session, id))
    } catch (err) {
      onError(errorText(err))
    }
  }

  async function lock() {
    if (selectedReport === null) return
    try {
      await collabApi.lockReport(session, selectedReport, lockDashboard, lockVersion)
      onNotice(`报告已锁定看板 ${lockDashboard} 的 v${lockVersion}，后续草稿与发布不再影响该引用`)
      await openReport(selectedReport)
    } catch (err) {
      onError(errorText(err))
    }
  }

  return (
    <div>
      <table className="data-table">
        <thead>
          <tr><th>报告 ID</th><th>名称</th><th>锁定版本</th><th>操作</th></tr>
        </thead>
        <tbody>
          {reports.map((r) => (
            <tr key={r.report_id}>
              <td>{r.report_id}</td>
              <td>{r.name}</td>
              <td>{r.lock ? `看板${r.lock.dashboard_id}@v${r.lock.version_no}` : '未锁定（引用会随布局漂移）'}</td>
              <td>
                <button type="button" className="link" onClick={() => void openReport(r.report_id)}>
                  查看引用与影响
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {isEditor && selectedReport !== null && (
        <div className="stat-card" style={{ marginTop: 12 }}>
          <h3>为报告 {selectedReport} 锁定确定版本</h3>
          <div className="filter-bar">
            <label className="filter-item">
              <span>看板</span>
              <select value={lockDashboard} onChange={(e) => setLockDashboard(Number(e.target.value))}>
                {dashboards.map((d) => (
                  <option key={d.dashboard_id} value={d.dashboard_id}>{d.dashboard_id} - {d.title}</option>
                ))}
              </select>
            </label>
            <label className="filter-item">
              <span>已发布版本号</span>
              <input
                type="number"
                min={1}
                value={lockVersion}
                onChange={(e) => setLockVersion(Number(e.target.value))}
              />
            </label>
            <button type="button" className="btn primary" onClick={() => void lock()}>
              锁定该版本
            </button>
          </div>
        </div>
      )}

      {detail && (
        <div className="stat-card" style={{ marginTop: 12 }}>
          <h3>{detail.name}（报告 {detail.report_id}）</h3>
          {detail.locked_layout ? (
            <>
              <p className="page-desc">
                锁定布局：看板 {detail.locked_layout.dashboard_id} v{detail.locked_layout.version_no}，
                部件 {detail.locked_layout.widgets.map((w) => w.widget_key).join('、')}
              </p>
              <table className="data-table">
                <thead><tr><th>部件标识</th><th>标题</th><th>类型</th><th>位置</th></tr></thead>
                <tbody>
                  {detail.locked_layout.widgets.map((w) => (
                    <tr key={w.widget_key}>
                      <td>{w.widget_key}</td>
                      <td>{w.title}</td>
                      <td>{w.type}</td>
                      <td>{`${w.position.x},${w.position.y},${w.position.w},${w.position.h}`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {detail.layout_impact && (
                <div className="stat-card" style={{ marginTop: 10 }}>
                  <strong>新版本影响评估</strong>
                  <p className="page-desc">{detail.layout_impact.explanation}</p>
                  <ul>
                    <li>最新草稿修订号：r{detail.layout_impact.latest_draft_revision}</li>
                    <li>最新发布版本：{detail.layout_impact.latest_published_version_no ? `v${detail.layout_impact.latest_published_version_no}` : '无'}</li>
                    <li>最新草稿中已删除的被引用部件：{detail.layout_impact.removed_in_latest_draft.join('、') || '无'}</li>
                    <li>最新发布版中已删除的被引用部件：{detail.layout_impact.removed_in_latest_published.join('、') || '无'}</li>
                  </ul>
                </div>
              )}
            </>
          ) : (
            <p className="page-desc">尚未锁定任何版本，报告引用无法保证可重复。</p>
          )}
        </div>
      )}
    </div>
  )
}

/* ---------------- 成员与权限 ---------------- */

function MembersTab({
  session,
  isEditor,
  onNotice,
  onError,
}: {
  session: ReturnType<typeof useCollabSession>[0]
  isEditor: boolean
  onNotice: (m: string) => void
  onError: (m: string) => void
}) {
  const [members, setMembers] = useState<Member[]>([])

  const load = useCallback(async () => {
    try {
      const resp = await collabApi.members(session)
      setMembers(resp.items)
    } catch (err) {
      onError(errorText(err))
    }
  }, [session, onError])

  useEffect(() => {
    void load()
  }, [load])

  async function toggle(member: Member) {
    try {
      if (member.active) {
        await collabApi.revoke(session, member.user_id)
        onNotice(`已撤销 ${member.display_name} 的成员资格：其之后的读取与提交都会被服务端拒绝`)
      } else {
        await collabApi.restore(session, member.user_id)
        onNotice(`已恢复 ${member.display_name} 的成员资格`)
      }
      await load()
    } catch (err) {
      onError(errorText(err))
    }
  }

  return (
    <div>
      <table className="data-table">
        <thead>
          <tr><th>用户 ID</th><th>姓名</th><th>角色</th><th>状态</th>{isEditor && <th>操作</th>}</tr>
        </thead>
        <tbody>
          {members.map((m) => (
            <tr key={m.user_id}>
              <td>{m.user_id}</td>
              <td>{m.display_name}</td>
              <td>{m.role === 'editor' ? '编辑者' : '只读成员'}</td>
              <td>{m.active ? '有效' : '已撤销'}</td>
              {isEditor && (
                <td>
                  <button type="button" className="link" onClick={() => void toggle(m)}>
                    {m.active ? '撤销权限' : '恢复权限'}
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {!isEditor && <p className="page-foot">只读成员不能变更成员关系，服务端会拒绝相关请求。</p>}
    </div>
  )
}
