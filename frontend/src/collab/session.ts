/**
 * 协作域会话：本地身份与工作空间选择。
 * 身份只保存在浏览器本地（localStorage），不依赖任何外部身份服务；
 * 真正的权限裁决在服务端，这里的状态仅用于决定带哪个请求头。
 */
import { useEffect, useState } from 'react'

export interface CollabSession {
  userId: string
  workspaceId: string
}

const STORAGE_KEY = 'collab-session'

export function loadSession(): CollabSession {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as CollabSession
      if (parsed.userId && parsed.workspaceId) return parsed
    }
  } catch {
    // 本地存储损坏时回落到默认演示身份
  }
  return { userId: 'u-alice', workspaceId: 'ws-a' }
}

export function saveSession(session: CollabSession): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
}

export function useCollabSession(): [CollabSession, (next: CollabSession) => void] {
  const [session, setSession] = useState<CollabSession>(loadSession)
  useEffect(() => {
    saveSession(session)
  }, [session])
  return [session, setSession]
}

export function authHeaders(session: CollabSession): Record<string, string> {
  return { 'X-User-Id': session.userId, 'X-Workspace-Id': session.workspaceId }
}
