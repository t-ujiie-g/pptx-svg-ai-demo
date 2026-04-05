import { useState, useRef, useCallback } from 'react'
import { ChatSession, Message, ToolUsage, FileAttachment, PptxArtifactData } from '../services/chatHistory'
import { config } from '../config'

export interface StreamEvent {
  type: 'tool_call' | 'tool_result' | 'text_chunk' | 'text' | 'done' | 'error' | 'pptx_artifact'
  tool?: string
  status?: string
  content?: string | Array<{ type: string; text?: string; data?: string; mimeType?: string }>
  message?: string
  artifact_id?: string
  filename?: string
  download_url?: string
  size_bytes?: number
}

export interface StreamingToolUsage {
  id: string
  name: string
  status: 'running' | 'completed'
  timestamp: number
}

export interface StreamingState {
  isStreaming: boolean
  currentTool: string | null
  toolHistory: StreamingToolUsage[]
  accumulatedText: string
  pptxArtifacts: PptxArtifactData[]
}

const INITIAL_STREAMING_STATE: StreamingState = {
  isStreaming: false,
  currentTool: null,
  toolHistory: [],
  accumulatedText: '',
  pptxArtifacts: [],
}

function getUserId(): string {
  let userId = localStorage.getItem(config.storage.userId)
  if (!userId) {
    userId = crypto.randomUUID()
    localStorage.setItem(config.storage.userId, userId)
  }
  return userId
}

export function useChat({
  onUpdateSession,
  onPptxArtifactChange,
}: {
  onUpdateSession: (session: ChatSession) => void
  onPptxArtifactChange?: (artifact: PptxArtifactData | null) => void
}) {
  const [isLoading, setIsLoading] = useState(false)
  const [streamingState, setStreamingState] = useState<StreamingState>(INITIAL_STREAMING_STATE)
  const abortControllerRef = useRef<AbortController | null>(null)

  const parseSSEEvent = useCallback((line: string): StreamEvent | null => {
    if (!line.startsWith('data: ')) return null
    try {
      return JSON.parse(line.slice(6)) as StreamEvent
    } catch {
      return null
    }
  }, [])

  const processStream = useCallback(
    async (
      reader: ReadableStreamDefaultReader<Uint8Array>,
      updatedSession: ChatSession,
      updatedMessages: Message[]
    ) => {
      const decoder = new TextDecoder()
      let accumulatedText = ''
      let buffer = ''
      const toolHistory: StreamingToolUsage[] = []
      const pptxArtifacts: PptxArtifactData[] = []

      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            const event = parseSSEEvent(line)
            if (!event) continue

            switch (event.type) {
              case 'tool_call': {
                const toolName = event.tool || 'unknown'
                toolHistory.push({ id: crypto.randomUUID(), name: toolName, status: 'running', timestamp: Date.now() })
                setStreamingState((prev) => ({ ...prev, currentTool: toolName, toolHistory: [...toolHistory] }))
                break
              }
              case 'tool_result': {
                const idx = toolHistory.findIndex((t) => t.name === event.tool && t.status === 'running')
                if (idx >= 0) toolHistory[idx] = { ...toolHistory[idx], status: 'completed' }
                setStreamingState((prev) => ({ ...prev, currentTool: null, toolHistory: [...toolHistory] }))
                break
              }
              case 'pptx_artifact': {
                if (event.artifact_id && event.download_url) {
                  const artifact: PptxArtifactData = {
                    artifactId: event.artifact_id,
                    filename: event.filename || 'presentation.pptx',
                    downloadUrl: event.download_url,
                    sizeBytes: event.size_bytes || 0,
                  }
                  pptxArtifacts.push(artifact)
                  setStreamingState((prev) => ({ ...prev, pptxArtifacts: [...pptxArtifacts] }))
                  onPptxArtifactChange?.(artifact)
                }
                break
              }
              case 'text_chunk':
              case 'text':
                if (event.content && typeof event.content === 'string') {
                  accumulatedText += event.content
                  setStreamingState((prev) => ({ ...prev, accumulatedText }))
                }
                break
              case 'error':
                throw new Error(event.message || 'ストリーミングエラー')
              case 'done':
                break
            }
          }
        }

        if (accumulatedText || pptxArtifacts.length > 0) {
          const completedTools: ToolUsage[] = toolHistory
            .filter((t) => t.status === 'completed')
            .map((t) => ({ id: t.id, name: t.name, status: 'completed' as const, timestamp: t.timestamp }))

          const assistantMessage: Message = {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: accumulatedText,
            timestamp: Date.now(),
            toolUsages: completedTools.length > 0 ? completedTools : undefined,
            pptxArtifacts: pptxArtifacts.length > 0 ? pptxArtifacts : undefined,
          }
          const nextSession = { ...updatedSession, messages: [...updatedMessages, assistantMessage] }
          onUpdateSession(nextSession)
        }
      } finally {
        setStreamingState(INITIAL_STREAMING_STATE)
      }
    },
    [parseSSEEvent, onUpdateSession, onPptxArtifactChange]
  )

  const sendMessage = async (
    input: string,
    attachedFiles: File[],
    session: ChatSession,
    onNewChat: () => void,
    createAttachmentMeta: (files: File[]) => Promise<FileAttachment[]>,
    pptxArtifactId?: string,
  ) => {
    if ((!input.trim() && attachedFiles.length === 0) || isLoading) return
    if (!session) { onNewChat(); return }

    const attachments = attachedFiles.length > 0 ? await createAttachmentMeta(attachedFiles) : undefined
    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: input,
      timestamp: Date.now(),
      attachments,
    }
    const updatedMessages = [...session.messages, userMessage]
    const updatedSession = { ...session, messages: updatedMessages }
    onUpdateSession(updatedSession)

    setIsLoading(true)
    setStreamingState({ ...INITIAL_STREAMING_STATE, isStreaming: true })
    abortControllerRef.current?.abort()
    abortControllerRef.current = new AbortController()

    try {
      let response: Response

      // Use multipart when there are files OR a pptxArtifactId to pass
      if (attachedFiles.length > 0 || pptxArtifactId) {
        const formData = new FormData()
        formData.append('text', input)
        formData.append('threadId', session.id)
        formData.append('userId', getUserId())
        if (pptxArtifactId) {
          formData.append('pptxArtifactId', pptxArtifactId)
        }
        for (const file of attachedFiles) formData.append('files', file)
        response = await fetch(`${config.api.baseUrl}${config.api.endpoints.chatStream}`, {
          method: 'POST', body: formData, signal: abortControllerRef.current.signal,
        })
      } else {
        response = await fetch(`${config.api.baseUrl}${config.api.endpoints.chatStream}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            messages: updatedMessages.map((m) => ({ role: m.role, content: m.content })),
            threadId: session.id,
            userId: getUserId(),
          }),
          signal: abortControllerRef.current.signal,
        })
      }

      if (!response.ok) throw new Error(`HTTP error: ${response.status}`)
      const reader = response.body?.getReader()
      if (!reader) throw new Error('ストリームの取得に失敗しました')

      await processStream(reader, updatedSession, updatedMessages)
    } catch (error) {
      if ((error as Error).name === 'AbortError') return
      onUpdateSession({
        ...updatedSession,
        messages: [...updatedMessages, {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: `通信エラーが発生しました: ${error}`,
          timestamp: Date.now(),
        }],
      })
      setStreamingState(INITIAL_STREAMING_STATE)
    } finally {
      setIsLoading(false)
    }
  }

  return { isLoading, streamingState, sendMessage }
}
