/**
 * アプリケーション設定
 */

export const config = {
  // バックエンドAPI
  api: {
    baseUrl: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
    endpoints: {
      chat: '/chat',
      chatStream: '/chat/stream',
      health: '/health',
      generateTemplate: '/prompts/generate-template',
    },
  },

  // アプリ情報
  app: {
    name: 'スライド作成AI',
    version: '0.1.0',
  },

  // ローカルストレージのキー
  storage: {
    theme: 'theme',
    userId: 'user-id',
  },

  // UI設定
  ui: {
    chatTitleMaxLength: 30,
    textareaMaxHeight: 200,
  },
} as const

/** Trigger a file download from an API path (e.g. /artifacts/{id}). */
export function downloadFromApi(apiPath: string, filename: string) {
  const link = document.createElement('a')
  link.href = `${config.api.baseUrl}${apiPath}`
  link.download = filename
  link.click()
}

// 型定義
export type Config = typeof config
export type Theme = 'light' | 'dark' | 'system'
