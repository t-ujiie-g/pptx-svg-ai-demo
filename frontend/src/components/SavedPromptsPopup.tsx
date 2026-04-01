import { useState, useEffect, useRef } from 'react'
import { SavedPrompt, savedPromptsService } from '../services/savedPrompts'
import './SavedPromptsPopup.css'

interface SavedPromptsPopupProps {
  onSelect: (content: string) => void
  onSelectTemplate?: (prompt: SavedPrompt) => void
  onCreate: (initialContent?: string) => void
  onEdit: (prompt: SavedPrompt) => void
  onClose: () => void
  currentInput?: string
}

export function SavedPromptsPopup({ onSelect, onSelectTemplate, onCreate, onEdit, onClose, currentInput }: SavedPromptsPopupProps) {
  const [prompts, setPrompts] = useState<SavedPrompt[]>([])
  const [search, setSearch] = useState('')
  const popupRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadPrompts()
  }, [])

  // click-outside で閉じる（トグルボタンのクリックは除外）
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as HTMLElement
      if (
        popupRef.current &&
        !popupRef.current.contains(target) &&
        !target.closest('.prompt-bookmark-btn')
      ) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [onClose])

  const loadPrompts = async () => {
    const all = await savedPromptsService.getAll()
    setPrompts(all)
  }

  const filteredPrompts = search
    ? prompts.filter((p) => p.name.toLowerCase().includes(search.toLowerCase()))
    : prompts

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    await savedPromptsService.delete(id)
    await loadPrompts()
  }

  const handleSelect = (prompt: SavedPrompt) => {
    const hasVariables = prompt.variables && prompt.variables.length > 0
    if (hasVariables && onSelectTemplate) {
      onSelectTemplate(prompt)
    } else {
      onSelect(prompt.content)
      onClose()
    }
  }

  return (
    <div className="saved-prompts-popup" ref={popupRef}>
      <div className="saved-prompts-header">
        <h3>保存プロンプト</h3>
        <button className="saved-prompts-add-btn" onClick={() => onCreate()}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 5v14M5 12h14" />
          </svg>
          新規作成
        </button>
      </div>

      {prompts.length >= 3 && (
        <div className="saved-prompts-search">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="プロンプトを検索..."
          />
        </div>
      )}

      <div className="saved-prompts-list">
        {filteredPrompts.length === 0 ? (
          <div className="saved-prompts-empty">
            {prompts.length === 0 ? '保存されたプロンプトはありません' : '一致するプロンプトがありません'}
          </div>
        ) : (
          filteredPrompts.map((prompt) => (
            <div
              key={prompt.id}
              className="saved-prompt-item"
              onClick={() => handleSelect(prompt)}
            >
              <div className="saved-prompt-item-content">
                <div className="saved-prompt-item-name">
                  {prompt.variables && prompt.variables.length > 0 && (
                    <span className="saved-prompt-template-badge">
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                        <path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z" />
                      </svg>
                    </span>
                  )}
                  {prompt.name}
                </div>
                <div className="saved-prompt-item-preview">{prompt.content}</div>
              </div>
              <div className="saved-prompt-item-actions">
                <button
                  className="saved-prompt-action-btn"
                  onClick={(e) => { e.stopPropagation(); onEdit(prompt) }}
                  aria-label="編集"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
                    <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
                  </svg>
                </button>
                <button
                  className="saved-prompt-action-btn delete"
                  onClick={(e) => handleDelete(e, prompt.id)}
                  aria-label="削除"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                  </svg>
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {currentInput?.trim() && (
        <button className="save-current-input-btn" onClick={() => onCreate(currentInput)}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z" />
            <polyline points="17 21 17 13 7 13 7 21" />
            <polyline points="7 3 7 8 15 8" />
          </svg>
          入力中のテキストを保存
        </button>
      )}
    </div>
  )
}
