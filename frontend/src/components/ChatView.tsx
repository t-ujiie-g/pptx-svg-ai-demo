import { useState, useRef, useEffect } from 'react'
import { ChatSession, PptxArtifactData } from '../services/chatHistory'
import { SavedPrompt } from '../services/savedPrompts'
import { useChat } from '../hooks/useChat'
import { useFileAttachment, ACCEPT_TYPES } from '../hooks/useFileAttachment'
import { useTemplateGeneration } from '../hooks/useTemplateGeneration'
import { ChatMessageList } from './ChatMessageList'
import { FilePreviewArea } from './FilePreviewArea'
import { ModeSelector } from './ModeSelector'
import { PipelineProgress } from './PipelineProgress'
import { TemplateConfirmModal } from './TemplateConfirmModal'
import { TemplateGeneratingOverlay } from './TemplateGeneratingOverlay'
import { SavedPromptsPopup } from './SavedPromptsPopup'
import { TemplateEditorModal } from './TemplateEditorModal'
import { TemplateExecuteModal } from './TemplateExecuteModal'
import { ModeSpec } from '../types/modeSpec'
import { config } from '../config'
import './ChatView.css'

interface ChatViewProps {
  session: ChatSession | null
  onUpdateSession: (session: ChatSession) => void
  onNewChat: () => void
  onPptxArtifactChange?: (artifact: PptxArtifactData | null) => void
  syncEditedPptx?: () => Promise<boolean>
  activePptxArtifactId?: string
}

export function ChatView({ session, onUpdateSession, onNewChat, onPptxArtifactChange, syncEditedPptx, activePptxArtifactId }: ChatViewProps) {
  const [input, setInput] = useState('')
  const [isComposing, setIsComposing] = useState(false)
  const [savedPromptsOpen, setSavedPromptsOpen] = useState(false)
  const [modeSpec, setModeSpec] = useState<ModeSpec | null>(null)
  const [styleRefFile, setStyleRefFile] = useState<File | null>(null)
  // バックエンドにアップロード済みのstyle_ref artifact IDを保持し、次回送信時に
  // 同じ参照を使い回せるようにする。新しい styleRefFile が選ばれた瞬間に消す。
  const [styleRefArtifactId, setStyleRefArtifactId] = useState<string | undefined>(undefined)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const { isLoading, streamingState, sendMessage } = useChat({
    sessionId: session?.id ?? null,
    onUpdateSession,
    onPptxArtifactChange,
  })

  const {
    attachedFiles, setAttachedFiles,
    addFiles, removeFile,
    handleFileSelect, handlePaste, handleDragOver, handleDrop,
    getPreviewUrl, createAttachmentMeta,
  } = useFileAttachment()

  const {
    isGeneratingTemplate, showTemplateConfirm, setShowTemplateConfirm,
    templateEditorData, templateEditId,
    templateExecuteTarget, setTemplateExecuteTarget,
    openSaveModal, openEditModal, generateTemplate, handleTemplateExecute, closeTemplateEditor,
  } = useTemplateGeneration(session, isLoading)

  // テキストエリアの高さ自動調整
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height =
        Math.min(textareaRef.current.scrollHeight, config.ui.textareaMaxHeight) + 'px'
    }
  }, [input])

  const handleSend = async () => {
    if (!session) { onNewChat(); return }
    // Push any frontend edits to the server's artifact store first so the
    // backend's context for activePptxArtifactId reflects the latest state.
    if (syncEditedPptx) {
      await syncEditedPptx()
    }
    sendMessage(
      input, attachedFiles, session, onNewChat, createAttachmentMeta, activePptxArtifactId,
      {
        modeSpec,
        styleRefFile,
        styleRefArtifactId,
      },
    )
    setInput('')
    setAttachedFiles([])
    // styleRefFile はクリアしない: backend から mode_spec SSE で artifact_id が
    // 返ってきたタイミングで sync 用 useEffect が安全にクリアする。
  }

  const handleSelectStyleRefFile = (file: File | null) => {
    setStyleRefFile(file)
    // ファイル選択 / クリアどちらでも過去の artifact_id を無効化
    setStyleRefArtifactId(undefined)
  }

  // backend が styleRefFile を保存し artifact_id を mode_spec SSE で返してきたら、
  // ローカル state に格納し、ファイルオブジェクトはクリア (次回 send で再送しない)。
  const appliedStyleRefArtifactId = streamingState.appliedStyleRefArtifactId
  useEffect(() => {
    if (appliedStyleRefArtifactId && appliedStyleRefArtifactId !== styleRefArtifactId) {
      setStyleRefArtifactId(appliedStyleRefArtifactId)
      setStyleRefFile(null)
    }
  }, [appliedStyleRefArtifactId, styleRefArtifactId])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (isComposing) return
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  if (!session) {
    return (
      <div className="chat-view empty">
        <div className="welcome-screen">
          <div className="welcome-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z" />
              <polyline points="13 2 13 9 20 9" />
            </svg>
          </div>
          <h1>スライド作成AI</h1>
          <p>AIがプレゼンテーションの作成をサポートします</p>
          <button className="start-chat-btn" onClick={onNewChat}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 5v14M5 12h14" />
            </svg>
            新しいチャットを開始
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="chat-view">
      <ChatMessageList
        messages={session.messages}
        isLoading={isLoading}
        streamingState={streamingState}
        onPptxArtifactChange={onPptxArtifactChange}
        onSavePrompt={openSaveModal}
      />

      <div className="input-container" onDragOver={handleDragOver} onDrop={handleDrop}>
        <div className="saved-prompts-anchor">
          {savedPromptsOpen && (
            <SavedPromptsPopup
              onSelect={(content) => setInput(content)}
              onSelectTemplate={(prompt: SavedPrompt) => {
                setSavedPromptsOpen(false)
                setTemplateExecuteTarget(prompt)
              }}
              onCreate={(initialContent) => {
                setSavedPromptsOpen(false)
                openSaveModal(initialContent || '')
              }}
              onEdit={(prompt: SavedPrompt) => {
                setSavedPromptsOpen(false)
                openEditModal(prompt)
              }}
              onClose={() => setSavedPromptsOpen(false)}
              currentInput={input}
            />
          )}

          <FilePreviewArea
            files={attachedFiles}
            onRemove={removeFile}
            getPreviewUrl={getPreviewUrl}
          />

          {/* パイプライン進捗 (style/preservation/critic/...). ストリーム中で
              なくても直前の結果が残っていれば表示。チャット上部に流されず
              入力欄のすぐ近くで常に視認できる位置。 */}
          <PipelineProgress state={streamingState} />

          <ModeSelector
            text={input}
            targetArtifactId={activePptxArtifactId}
            styleRefArtifactId={styleRefArtifactId}
            modeSpec={modeSpec}
            onChangeModeSpec={setModeSpec}
            styleRefFile={styleRefFile}
            onSelectStyleRefFile={handleSelectStyleRefFile}
            disabled={isLoading}
          />

          <div className="input-wrapper">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              onCompositionStart={() => setIsComposing(true)}
              onCompositionEnd={() => setIsComposing(false)}
              onPaste={handlePaste}
              placeholder="スライドの内容を入力..."
              disabled={isLoading}
              rows={1}
            />
            <div className="input-actions">
              <div className="input-actions-left">
                <button
                  className="attach-btn"
                  onClick={() => fileInputRef.current?.click()}
                  aria-label="ファイルを添付"
                  disabled={isLoading}
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M12 5v14M5 12h14" />
                  </svg>
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept={ACCEPT_TYPES}
                  onChange={handleFileSelect}
                  hidden
                />
                <button
                  className="prompt-bookmark-btn"
                  onClick={() => setSavedPromptsOpen(!savedPromptsOpen)}
                  aria-label="保存プロンプト"
                  aria-expanded={savedPromptsOpen}
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z" />
                  </svg>
                </button>
                {session.messages.length >= 2 && (
                  <button
                    className="generate-template-btn"
                    onClick={() => setShowTemplateConfirm(true)}
                    disabled={isLoading || isGeneratingTemplate}
                    aria-label="テンプレート生成"
                    title="この会話からテンプレートを生成"
                  >
                    {isGeneratingTemplate ? (
                      <svg className="generating-spinner" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <circle cx="12" cy="12" r="10" />
                        <path d="M12 6v6l4 2" />
                      </svg>
                    ) : (
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z" />
                      </svg>
                    )}
                  </button>
                )}
              </div>
              <button
                className="send-btn"
                onClick={handleSend}
                disabled={isLoading || (!input.trim() && attachedFiles.length === 0)}
                aria-label="Send message"
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
                </svg>
              </button>
            </div>
          </div>
        </div>
        <p className="input-hint">Enterで送信 / Shift+Enterで改行</p>

        {showTemplateConfirm && (
          <TemplateConfirmModal
            onConfirm={() => { setShowTemplateConfirm(false); generateTemplate() }}
            onCancel={() => setShowTemplateConfirm(false)}
          />
        )}
        {isGeneratingTemplate && <TemplateGeneratingOverlay />}
        {templateEditorData && (
          <TemplateEditorModal
            initialData={templateEditorData}
            editId={templateEditId}
            sessionId={session.id}
            onSave={closeTemplateEditor}
            onClose={closeTemplateEditor}
          />
        )}
        {templateExecuteTarget && (
          <TemplateExecuteModal
            template={templateExecuteTarget}
            onExecute={(resolvedContent, files) =>
              handleTemplateExecute(resolvedContent, files, setInput, addFiles)
            }
            onClose={() => setTemplateExecuteTarget(null)}
          />
        )}
      </div>
    </div>
  )
}
