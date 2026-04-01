/**
 * 保存プロンプトサービス
 *
 * localStorageを使用して保存プロンプトを永続化します。
 */

const STORAGE_KEY = 'saved-prompts'

export interface TemplateVariable {
  name: string
  label: string
  description: string
  defaultValue: string
  type?: 'text' | 'file'
}

export interface SavedPrompt {
  id: string
  name: string
  content: string
  createdAt: number
  updatedAt: number
  isTemplate?: boolean
  variables?: TemplateVariable[]
  sourceSessionId?: string
}

function loadPrompts(): SavedPrompt[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function savePrompts(prompts: SavedPrompt[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(prompts))
}

export const savedPromptsService = {
  async getAll(): Promise<SavedPrompt[]> {
    const prompts = loadPrompts()
    return [...prompts].sort((a, b) => b.updatedAt - a.updatedAt)
  },

  async create(name: string, content: string): Promise<SavedPrompt> {
    const prompt: SavedPrompt = {
      id: crypto.randomUUID(),
      name,
      content,
      createdAt: Date.now(),
      updatedAt: Date.now(),
    }
    const prompts = loadPrompts()
    prompts.unshift(prompt)
    savePrompts(prompts)
    return prompt
  },

  async update(id: string, updates: Partial<Pick<SavedPrompt, 'name' | 'content' | 'variables' | 'isTemplate'>>): Promise<void> {
    const prompts = loadPrompts()
    const index = prompts.findIndex((p) => p.id === id)
    if (index >= 0) {
      prompts[index] = {
        ...prompts[index],
        ...updates,
        updatedAt: Date.now(),
      }
      savePrompts(prompts)
    }
  },

  async createTemplate(
    name: string,
    content: string,
    variables: TemplateVariable[],
    sourceSessionId?: string
  ): Promise<SavedPrompt> {
    const prompt: SavedPrompt = {
      id: crypto.randomUUID(),
      name,
      content,
      createdAt: Date.now(),
      updatedAt: Date.now(),
      isTemplate: true,
      variables,
      sourceSessionId,
    }
    const prompts = loadPrompts()
    prompts.unshift(prompt)
    savePrompts(prompts)
    return prompt
  },

  async delete(id: string): Promise<void> {
    const prompts = loadPrompts()
    const filtered = prompts.filter((p) => p.id !== id)
    savePrompts(filtered)
  },
}
