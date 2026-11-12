/** 布局协作域接口封装：统一注入本地身份/工作空间请求头并解析后端错误。 */
import { request } from '@/api/client'

import { authHeaders, type CollabSession } from './session'

export interface CollabApiError extends Error {
  status: number
  details?: unknown
}

async function call<T>(
  session: CollabSession,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await request(path, {
    ...init,
    headers: { ...authHeaders(session), ...(init?.headers ?? {}) },
  })
  if (response.ok) {
    return (await response.json()) as T
  }
  let payload: { detail?: string; details?: unknown } = {}
  try {
    payload = await response.json()
  } catch {
    // 非 JSON 错误响应，保留通用信息
  }
  const error = new Error(payload.detail ?? `请求失败（${response.status}）`) as CollabApiError
  error.status = response.status
  error.details = payload.details
  throw error
}

export const collabApi = {
  me: (s: CollabSession) => call(s, '/api/collab/me'),
  workspaces: (s: CollabSession) =>
    call<{ items: Array<{ workspace_id: string; name: string; role: string }> }>(s, '/api/collab/workspaces'),
  members: (s: CollabSession) =>
    call<{ items: Array<{ user_id: string; display_name: string; role: string; active: boolean }> }>(
      s,
      '/api/collab/members',
    ),
  revoke: (s: CollabSession, userId: string) =>
    call(s, `/api/collab/members/${encodeURIComponent(userId)}/revoke`, { method: 'POST' }),
  restore: (s: CollabSession, userId: string) =>
    call(s, `/api/collab/members/${encodeURIComponent(userId)}/restore`, { method: 'POST' }),

  dashboards: (s: CollabSession) =>
    call<{ items: DashboardSummary[] }>(s, '/api/collab/dashboards'),
  draft: (s: CollabSession, id: number) =>
    call<{ dashboard_id: number; title: string; draft: DraftState }>(
      s,
      `/api/collab/dashboards/${id}/draft`,
    ),
  submitDraft: (s: CollabSession, id: number, body: unknown) =>
    call<SubmitResult>(s, `/api/collab/dashboards/${id}/draft`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  resolveConflict: (s: CollabSession, id: number, body: unknown) =>
    call(s, `/api/collab/dashboards/${id}/conflict-resolution`, { method: 'POST', body: JSON.stringify(body) }),
  addWidget: (s: CollabSession, id: number, body: unknown) =>
    call(s, `/api/collab/dashboards/${id}/widgets`, { method: 'POST', body: JSON.stringify(body) }),
  publish: (s: CollabSession, id: number, body: unknown) =>
    call<PublishResult>(s, `/api/collab/dashboards/${id}/publish`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  versions: (s: CollabSession, id: number) =>
    call<{ items: VersionSummary[] }>(s, `/api/collab/dashboards/${id}/versions`),
  latestPublished: (s: CollabSession, id: number) =>
    call<PublishedVersion>(s, `/api/collab/dashboards/${id}/published/latest`),
  createShareToken: (s: CollabSession, id: number, versionNo: number) =>
    call<{ token: string }>(s, `/api/collab/dashboards/${id}/versions/${versionNo}/share-tokens`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),

  reports: (s: CollabSession) => call<{ items: ReportSummary[] }>(s, '/api/collab/reports'),
  lockReport: (s: CollabSession, reportId: number, dashboardId: number, versionNo: number) =>
    call(s, `/api/collab/reports/${reportId}/lock`, {
      method: 'POST',
      body: JSON.stringify({ dashboard_id: dashboardId, version_no: versionNo }),
    }),
  report: (s: CollabSession, reportId: number) =>
    call<ReportDetail>(s, `/api/collab/reports/${reportId}`),
}

export interface Position {
  x: number
  y: number
  w: number
  h: number
}

export interface Widget {
  widget_key: string
  title: string
  type: string
  position: Position
  config: Record<string, unknown>
}

export interface DraftState {
  revision: number
  base_version_no: number
  widgets: Widget[]
  updated_by: string
  updated_at: string
  last_change_summary: string
  history: Array<{ revision: number; by: string; at: string; summary: string }>
}

export interface DashboardSummary {
  dashboard_id: number
  title: string
  draft_revision: number
  published_revision: number
  published_versions: number
  last_updated_by: string
  last_updated_at: string
}

export interface VersionSummary {
  version_no: number
  revision: number
  widget_count: number
  widget_keys: string[]
  access_scope: { type: string; workspace_id: string; members?: string[] }
  published_by: string
  published_at: string
  change_note: string
}

export interface PublishedVersion extends VersionSummary {
  workspace_id: string
  dashboard_id: number
  widgets: Widget[]
  revision: number
  published_at: string
}

export interface SubmitResult {
  dashboard_id: number
  draft_revision: number
  merged: boolean
  decisions: Array<Record<string, unknown>>
  conflicts: Array<Record<string, unknown>>
}

export interface PublishResult {
  idempotent: boolean
  reason?: string
  version: PublishedVersion
}

export interface ReportSummary {
  report_id: number
  workspace_id: string
  name: string
  lock: { dashboard_id: number; version_no: number; locked_at: string } | null
  updated_by: string
}

export interface ReportDetail extends ReportSummary {
  locked_layout: PublishedVersion | null
  layout_impact: {
    locked_version_no: number
    latest_draft_revision: number
    latest_published_version_no: number | null
    removed_in_latest_draft: string[]
    removed_in_latest_published: string[]
    explanation: string
  } | null
}
