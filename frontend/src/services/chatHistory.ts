/**
 * チャット履歴サービス
 *
 * localStorageを使用してチャット履歴を永続化します。
 */

import { config } from '../config'

/** ツール使用履歴 */
export interface ToolUsage {
  id: string
  name: string
  status: 'completed'
  timestamp: number
}

/** PPTXアーティファクトデータ */
export interface PptxArtifactData {
  artifactId: string
  filename: string
  downloadUrl: string
  sizeBytes: number
}

/** 添付ファイルメタデータ */
export interface FileAttachment {
  name: string
  type: string // MIME type
  size: number
  previewUrl?: string // 画像の場合、data URL（小サイズのみ）
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  /** アシスタントメッセージのツール使用履歴（オプション） */
  toolUsages?: ToolUsage[]
  /** 添付ファイルメタデータ（オプション） */
  attachments?: FileAttachment[]
  /** PPTXアーティファクト（オプション） */
  pptxArtifacts?: PptxArtifactData[]
}

export interface ChatSession {
  id: string
  title: string
  messages: Message[]
  createdAt: number
  updatedAt: number
}

const STORAGE_KEY = 'chat-history'

function loadSessions(): ChatSession[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveSessions(sessions: ChatSession[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions))
}

export const chatHistoryService = {
  async getAllSessions(): Promise<ChatSession[]> {
    const sessions = loadSessions()
    return [...sessions].sort((a, b) => b.updatedAt - a.updatedAt)
  },

  async getSession(id: string): Promise<ChatSession | null> {
    const sessions = loadSessions()
    return sessions.find((s) => s.id === id) || null
  },

  async createSession(): Promise<ChatSession> {
    const session: ChatSession = {
      id: crypto.randomUUID(),
      title: '新しいチャット',
      messages: [],
      createdAt: Date.now(),
      updatedAt: Date.now(),
    }
    const sessions = loadSessions()
    sessions.unshift(session)
    saveSessions(sessions)
    return session
  },

  async saveSession(session: ChatSession): Promise<void> {
    const sessions = loadSessions()
    const index = sessions.findIndex((s) => s.id === session.id)

    session.updatedAt = Date.now()

    // Generate title from first user message if not set
    if (session.title === '新しいチャット' && session.messages.length > 0) {
      const firstUserMsg = session.messages.find((m) => m.role === 'user')
      if (firstUserMsg) {
        const maxLen = config.ui.chatTitleMaxLength
        session.title =
          firstUserMsg.content.slice(0, maxLen) +
          (firstUserMsg.content.length > maxLen ? '...' : '')
      }
    }

    if (index >= 0) {
      sessions[index] = session
    } else {
      sessions.unshift(session)
    }

    saveSessions(sessions)
  },

  async deleteSession(id: string): Promise<void> {
    const sessions = loadSessions()
    const filtered = sessions.filter((s) => s.id !== id)
    saveSessions(filtered)
  },

  async clearAll(): Promise<void> {
    localStorage.removeItem(STORAGE_KEY)
  },
}
