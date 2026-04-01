import { useRef, useEffect } from 'react'
import { Message, PptxArtifactData } from '../services/chatHistory'
import { StreamingState } from '../hooks/useChat'
import { MarkdownRenderer } from './MarkdownRenderer'
import { CollapsibleToolHistory } from './CollapsibleToolHistory'
import { downloadFromApi } from '../config'
import { formatFileSize, getFileIcon } from '../hooks/useFileAttachment'

interface ChatMessageListProps {
  messages: Message[]
  isLoading: boolean
  streamingState: StreamingState
  onPptxArtifactChange?: (artifact: PptxArtifactData | null) => void
  onSavePrompt: (content: string) => void
}

function PptxArtifactIndicator({ artifact, onClick }: { artifact: PptxArtifactData; onClick: () => void }) {
  const handleDownload = (e: React.MouseEvent) => {
    e.stopPropagation()
    downloadFromApi(artifact.downloadUrl, artifact.filename)
  }

  return (
    <div className="pptx-artifact-indicator" onClick={onClick}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z" />
        <polyline points="13 2 13 9 20 9" />
      </svg>
      <span>{artifact.filename}</span>
      <button className="pptx-artifact-download" onClick={handleDownload} title="ダウンロード">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
      </button>
    </div>
  )
}

export function ChatMessageList({
  messages,
  isLoading,
  streamingState,
  onPptxArtifactChange,
  onSavePrompt,
}: ChatMessageListProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <div className="messages-container">
      {messages.length === 0 ? (
        <div className="empty-chat">
          <p>メッセージを入力してチャットを開始してください</p>
        </div>
      ) : (
        messages.map((message) => (
          <div key={message.id} className={`message ${message.role}`}>
            <div className="message-avatar">
              {message.role === 'user' ? (
                <div className="avatar user-avatar">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
                    <circle cx="12" cy="7" r="4" />
                  </svg>
                </div>
              ) : (
                <div className="avatar assistant-avatar">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/>
                  </svg>
                </div>
              )}
            </div>
            <div className="message-content">
              {message.role === 'assistant' ? (
                <>
                  {message.toolUsages && message.toolUsages.length > 0 && (
                    <CollapsibleToolHistory toolUsages={message.toolUsages} />
                  )}
                  {message.pptxArtifacts && message.pptxArtifacts.map((artifact) => (
                    <PptxArtifactIndicator
                      key={artifact.artifactId}
                      artifact={artifact}
                      onClick={() => onPptxArtifactChange?.(artifact)}
                    />
                  ))}
                  <MarkdownRenderer content={message.content} />
                </>
              ) : (
                <>
                  <div className="message-text">{message.content}</div>
                  {message.attachments && message.attachments.length > 0 && (
                    <div className="message-attachments">
                      {message.attachments.map((att, idx) => (
                        <div key={idx} className="attachment-chip">
                          {att.previewUrl ? (
                            <img className="attachment-thumb" src={att.previewUrl} alt={att.name} />
                          ) : (
                            <span className="attachment-icon">{getFileIcon(att.type)}</span>
                          )}
                          <span className="attachment-name">{att.name}</span>
                          <span className="attachment-size">{formatFileSize(att.size)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="message-actions">
                    <button
                      className="save-prompt-btn"
                      onClick={() => onSavePrompt(message.content)}
                      aria-label="プロンプトとして保存"
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z" />
                      </svg>
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        ))
      )}

      {isLoading && (
        <div className="message assistant">
          <div className="message-avatar">
            <div className="avatar assistant-avatar">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/>
              </svg>
            </div>
          </div>
          <div className="message-content">
            {streamingState.toolHistory.length > 0 && (
              <div className="tool-history">
                {streamingState.toolHistory.map((tool) => (
                  <div key={tool.id} className={`tool-status ${tool.status}`}>
                    <span className="tool-icon">
                      {tool.status === 'running' ? (
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <circle cx="12" cy="12" r="10" />
                          <path d="M12 6v6l4 2" />
                        </svg>
                      ) : (
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M20 6L9 17l-5-5" />
                        </svg>
                      )}
                    </span>
                    <span className="tool-name">{tool.name}</span>
                    <span className="tool-label">{tool.status === 'running' ? 'を実行中...' : '完了'}</span>
                  </div>
                ))}
              </div>
            )}
            {streamingState.pptxArtifacts.map((artifact) => (
              <PptxArtifactIndicator
                key={artifact.artifactId}
                artifact={artifact}
                onClick={() => onPptxArtifactChange?.(artifact)}
              />
            ))}
            {streamingState.accumulatedText ? (
              <MarkdownRenderer content={streamingState.accumulatedText} />
            ) : (
              <div className="typing-indicator">
                <span></span><span></span><span></span>
              </div>
            )}
          </div>
        </div>
      )}

      <div ref={messagesEndRef} />
    </div>
  )
}
