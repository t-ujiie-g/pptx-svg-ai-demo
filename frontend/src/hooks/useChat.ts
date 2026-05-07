import { useState, useRef, useCallback, useEffect } from 'react'
import { ChatSession, Message, ToolUsage, FileAttachment, PptxArtifactData } from '../services/chatHistory'
import { savePptx as savePptxToOpfs } from '../services/pptxStorage'
import { ModeSpec } from '../types/modeSpec'
import { config } from '../config'

export interface StyleExtractedSummary {
  palette: Record<string, string>
  header_font: string
  body_font: string
  tone_tags: string[]
  template_kinds: string[]
}

export interface PreservationMissing {
  type: string
  value: string
  source_slide_idx: number
}

export interface PreservationScoreData {
  threshold: number
  matched: number
  total: number
  ratio: number
  missing: PreservationMissing[]
  passed: boolean
}

export interface CriticIssueData {
  slide: number | null
  shape_idx: number | null
  kind: string
  msg: string
}

export interface CriticScoresData {
  intent_fit: number
  design: number
  consistency: number
  info_density: number
  preservation: number
}

export type CriticVerdict = 'accept' | 'retry' | 'reject'

export interface CriticResultData {
  scores: CriticScoresData
  issues: CriticIssueData[]
  verdict: CriticVerdict
  retry_hint: string
  weighted: number | null
}

export interface StreamEvent {
  type:
    | 'tool_call'
    | 'tool_result'
    | 'text_chunk'
    | 'text'
    | 'done'
    | 'error'
    | 'pptx_artifact'
    | 'mode_spec'
    | 'style_extracted'
    | 'preservation'
    | 'critic_result'
    | 'pipeline_step'
    | 'pairwise_compare'
    | 'rollback'
  tool?: string
  status?: string
  content?: string | Array<{ type: string; text?: string; data?: string; mimeType?: string }>
  message?: string
  artifact_id?: string
  filename?: string
  download_url?: string
  size_bytes?: number
  // mode_spec event payload
  applied?: ModeSpec
  target_artifact_id?: string | null
  style_ref_artifact_id?: string | null
  // style_extracted event payload
  source_artifact_id?: string
  role?: string
  summary?: StyleExtractedSummary
  error?: string
  // preservation event payload
  intent?: string
  output_artifact_id?: string
  score?: PreservationScoreData
  // critic_result event payload
  result?: CriticResultData
  // pipeline_step event payload
  step?: string
  // pairwise_compare event payload
  v1_artifact_id?: string
  v2_artifact_id?: string
  winner?: 'v1' | 'v2' | 'tie'
  reasoning?: string
  // rollback event payload
  to_artifact_id?: string
  reason?: string
}

export interface StreamingToolUsage {
  id: string
  name: string
  status: 'running' | 'completed'
  timestamp: number
}

export interface StyleExtractedState {
  status: 'completed' | 'failed'
  sourceArtifactId: string
  role: string
  summary?: StyleExtractedSummary
  error?: string
}

export interface PreservationState {
  status: 'completed' | 'failed'
  intent: string
  outputArtifactId: string
  score?: PreservationScoreData
  error?: string
}

export interface CriticState {
  status: 'completed' | 'failed'
  intent: string
  outputArtifactId: string
  result?: CriticResultData
  error?: string
}

export interface PairwiseCompareState {
  status: 'completed' | 'failed'
  intent: string
  v1ArtifactId: string
  v2ArtifactId: string
  winner: 'v1' | 'v2' | 'tie'
  reasoning?: string
  error?: string
}

export interface RollbackState {
  toArtifactId: string
  reason: string
}

export interface PipelineStepState {
  step: string
}

export interface StreamingState {
  isStreaming: boolean
  currentTool: string | null
  toolHistory: StreamingToolUsage[]
  accumulatedText: string
  pptxArtifacts: PptxArtifactData[]
  /** バックエンドが確定した最新の ModeSpec（auto推定 or ユーザー上書き） */
  appliedModeSpec: ModeSpec | null
  /** mode_spec SSE で確定した target/style_ref artifact id (最新リクエスト分) */
  appliedTargetArtifactId: string | null
  appliedStyleRefArtifactId: string | null
  /** スタイル抽出結果（Phase 2）。当該リクエストで抽出が走った場合のみセット */
  styleExtracted: StyleExtractedState | null
  /** 情報保全チェック結果（Phase 3）。polish/restructure 時のみ走る */
  preservation: PreservationState | null
  /** Critic レビュー結果（Phase 4）。出力アーティファクトがある時のみ走る */
  critic: CriticState | null
  /** verdict=retry → 再生成された v2 の Critic 結果（Phase 4.5） */
  criticV2: CriticState | null
  /** v1 vs v2 のペアワイズ比較結果（Phase 4.5） */
  pairwise: PairwiseCompareState | null
  /** rollback 通知。pairwise で v1 が選ばれたとき発火（Phase 4.5） */
  rollback: RollbackState | null
  /** retry 開始などパイプライン進行ステップ（Phase 4.5） */
  pipelineStep: PipelineStepState | null
}

const INITIAL_STREAMING_STATE: StreamingState = {
  isStreaming: false,
  currentTool: null,
  toolHistory: [],
  accumulatedText: '',
  pptxArtifacts: [],
  appliedModeSpec: null,
  appliedTargetArtifactId: null,
  appliedStyleRefArtifactId: null,
  styleExtracted: null,
  preservation: null,
  critic: null,
  criticV2: null,
  pairwise: null,
  rollback: null,
  pipelineStep: null,
}

function getUserId(): string {
  let userId = localStorage.getItem(config.storage.userId)
  if (!userId) {
    userId = crypto.randomUUID()
    localStorage.setItem(config.storage.userId, userId)
  }
  return userId
}

/** Background-fetch a fresh artifact and persist it to OPFS. Best-effort. */
async function persistArtifactToOpfs(
  sessionId: string,
  artifact: PptxArtifactData,
): Promise<void> {
  try {
    const resp = await fetch(`${config.api.baseUrl}${artifact.downloadUrl}`)
    if (!resp.ok) {
      console.warn(
        `[opfs] failed to download artifact ${artifact.artifactId}: ${resp.status}`,
      )
      return
    }
    const blob = await resp.blob()
    await savePptxToOpfs(sessionId, artifact.artifactId, artifact.filename, blob)
  } catch (e) {
    console.warn(`[opfs] persist failed for ${artifact.artifactId}:`, e)
  }
}

export function useChat({
  sessionId,
  onUpdateSession,
  onPptxArtifactChange,
}: {
  /** 現在表示中のチャット ID。切り替わったら in-flight リクエストを abort し、
   *  pipeline state をリセットして他チャットへの汚染を防ぐ。 */
  sessionId: string | null
  onUpdateSession: (session: ChatSession) => void
  onPptxArtifactChange?: (artifact: PptxArtifactData | null) => void
}) {
  const [isLoading, setIsLoading] = useState(false)
  const [streamingState, setStreamingState] = useState<StreamingState>(INITIAL_STREAMING_STATE)
  const abortControllerRef = useRef<AbortController | null>(null)
  // 送信時にロックした sessionId。SSE 受信時にこれと現 sessionId を比較して、
  // 切替後の遅延イベントが他チャットへ波及するのを防ぐ。
  const streamSessionRef = useRef<string | null>(null)
  const currentSessionIdRef = useRef<string | null>(sessionId)
  currentSessionIdRef.current = sessionId

  // セッション切替: 進行中のストリームを止め、pipeline state を初期化する。
  // これをやらないと、Chat A の SSE pptx_artifact が Chat B の preview を
  // 上書きしてしまう (cross-chat contamination)。
  useEffect(() => {
    abortControllerRef.current?.abort()
    abortControllerRef.current = null
    streamSessionRef.current = null
    setIsLoading(false)
    setStreamingState(INITIAL_STREAMING_STATE)
  }, [sessionId])

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
                  // ストリーム開始時の session と現在の session が一致しているときだけ
                  // 親 layout の active artifact を更新する。切替後の遅延イベントで
                  // 他チャットの preview を上書きしないようにする防御。
                  if (
                    streamSessionRef.current !== null &&
                    streamSessionRef.current === currentSessionIdRef.current
                  ) {
                    onPptxArtifactChange?.(artifact)
                  }
                  // バックグラウンドで OPFS に保存。バックエンドの artifact_store
                  // は 1h TTL なので、リロード後も古い世代を辿れるようローカルにも
                  // コピー。await しないので SSE 処理を遅らせない。
                  const lockedSession = streamSessionRef.current
                  if (lockedSession) {
                    void persistArtifactToOpfs(lockedSession, artifact)
                  }
                }
                break
              }
              case 'mode_spec': {
                if (event.applied) {
                  setStreamingState((prev) => ({
                    ...prev,
                    appliedModeSpec: event.applied!,
                    appliedTargetArtifactId: event.target_artifact_id ?? null,
                    appliedStyleRefArtifactId: event.style_ref_artifact_id ?? null,
                  }))
                }
                break
              }
              case 'style_extracted': {
                if (event.status && event.source_artifact_id && event.role) {
                  const next: StyleExtractedState = {
                    status: event.status as 'completed' | 'failed',
                    sourceArtifactId: event.source_artifact_id,
                    role: event.role,
                    summary: event.summary,
                    error: event.error,
                  }
                  setStreamingState((prev) => ({ ...prev, styleExtracted: next }))
                }
                break
              }
              case 'preservation': {
                if (event.status && event.intent && event.output_artifact_id) {
                  const next: PreservationState = {
                    status: event.status as 'completed' | 'failed',
                    intent: event.intent,
                    outputArtifactId: event.output_artifact_id,
                    score: event.score,
                    error: event.error,
                  }
                  setStreamingState((prev) => ({ ...prev, preservation: next }))
                }
                break
              }
              case 'critic_result': {
                if (event.status && event.intent && event.output_artifact_id) {
                  const next: CriticState = {
                    status: event.status as 'completed' | 'failed',
                    intent: event.intent,
                    outputArtifactId: event.output_artifact_id,
                    result: event.result,
                    error: event.error,
                  }
                  // 2 回目の critic_result（v2 評価）は criticV2 に格納
                  setStreamingState((prev) =>
                    prev.critic === null
                      ? { ...prev, critic: next }
                      : { ...prev, criticV2: next }
                  )
                }
                break
              }
              case 'pipeline_step': {
                if (event.step) {
                  setStreamingState((prev) => ({
                    ...prev,
                    pipelineStep: { step: event.step! },
                  }))
                }
                break
              }
              case 'pairwise_compare': {
                if (event.v1_artifact_id && event.v2_artifact_id && event.winner) {
                  const next: PairwiseCompareState = {
                    status: (event.status as 'completed' | 'failed') || 'completed',
                    intent: event.intent || '',
                    v1ArtifactId: event.v1_artifact_id,
                    v2ArtifactId: event.v2_artifact_id,
                    winner: event.winner,
                    reasoning: event.reasoning,
                    error: event.error,
                  }
                  setStreamingState((prev) => ({ ...prev, pairwise: next }))
                }
                break
              }
              case 'rollback': {
                if (event.to_artifact_id) {
                  setStreamingState((prev) => ({
                    ...prev,
                    rollback: {
                      toArtifactId: event.to_artifact_id!,
                      reason: event.reason || '',
                    },
                  }))
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
        // ストリーム終了時、進行中表示用のフィールドだけクリアする。
        // pipeline 結果 (mode/style/preservation/critic/...) は次の送信まで
        // 入力欄上のチップで残し続け、ユーザーが verdict を見られるように。
        setStreamingState((prev) => ({
          ...prev,
          isStreaming: false,
          currentTool: null,
          accumulatedText: '',
          toolHistory: [],
          pptxArtifacts: [],
        }))
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
    options?: {
      modeSpec?: ModeSpec | null
      styleRefFile?: File | null
      styleRefArtifactId?: string
    },
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
    streamSessionRef.current = session.id

    try {
      let response: Response

      const useMultipart =
        attachedFiles.length > 0 ||
        !!pptxArtifactId ||
        !!options?.modeSpec ||
        !!options?.styleRefFile ||
        !!options?.styleRefArtifactId

      if (useMultipart) {
        const formData = new FormData()
        formData.append('text', input)
        formData.append('threadId', session.id)
        formData.append('userId', getUserId())
        if (pptxArtifactId) {
          formData.append('pptxArtifactId', pptxArtifactId)
        }
        if (options?.modeSpec) {
          formData.append('modeSpec', JSON.stringify(options.modeSpec))
        }
        if (options?.styleRefArtifactId) {
          formData.append('styleRefArtifactId', options.styleRefArtifactId)
        }
        if (options?.styleRefFile) {
          formData.append('styleRefFile', options.styleRefFile)
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
