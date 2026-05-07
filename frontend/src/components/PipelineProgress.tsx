import { StreamingState } from '../hooks/useChat'
import { INTENT_LABELS, STYLE_SOURCE_KIND_LABELS } from '../types/modeSpec'
import './PipelineProgress.css'

interface Props {
  state: StreamingState
}

type Status = 'pending' | 'running' | 'completed' | 'failed' | 'warn'

interface StepChip {
  label: string
  status: Status
  detail?: string
  hint?: string
}

/**
 * パイプライン進捗をリアルタイムに表示するインラインバー。
 * ストリーミング中のアシスタント吹き出し内に置き、SSE が届くたびに状態が
 * 進む。バッファリングされて急に更新される現象を、各ステップの可視化で
 * 解消する狙い。
 */
export function PipelineProgress({ state }: Props) {
  const chips = buildChips(state)
  const visible = chips.filter((c) => c.status !== 'pending')
  if (visible.length === 0) return null

  return (
    <div className="pipeline-progress">
      {chips.map((chip, i) => (
        <div key={i} className={`pipeline-chip pipeline-chip--${chip.status}`} title={chip.hint}>
          <span className="pipeline-chip__dot" />
          <span className="pipeline-chip__label">{chip.label}</span>
          {chip.detail && <span className="pipeline-chip__detail">{chip.detail}</span>}
        </div>
      ))}
    </div>
  )
}

function buildChips(s: StreamingState): StepChip[] {
  const chips: StepChip[] = []

  // モード確定
  if (s.appliedModeSpec) {
    const m = s.appliedModeSpec
    const detail = `${INTENT_LABELS[m.intent]} / ${STYLE_SOURCE_KIND_LABELS[m.style_source.kind]}`
    chips.push({ label: 'モード', status: 'completed', detail })
  } else {
    chips.push({ label: 'モード', status: 'pending' })
  }

  // スタイル抽出
  if (s.styleExtracted) {
    if (s.styleExtracted.status === 'completed') {
      const tk = s.styleExtracted.summary?.template_kinds || []
      const detail = tk.length > 0 ? `${tk.length}テンプレ抽出` : 'Layer A 抽出'
      chips.push({ label: 'スタイル抽出', status: 'completed', detail, hint: tk.join(', ') })
    } else {
      chips.push({
        label: 'スタイル抽出', status: 'failed', detail: '失敗',
        hint: s.styleExtracted.error,
      })
    }
  }

  // 保全チェック (v1)
  if (s.preservation) {
    if (s.preservation.status === 'completed' && s.preservation.score) {
      const sc = s.preservation.score
      const status: Status = sc.passed ? 'completed' : 'warn'
      chips.push({
        label: '保全チェック',
        status,
        detail: `${sc.matched}/${sc.total} (${(sc.ratio * 100).toFixed(0)}%)`,
        hint: sc.passed ? '合格' : `欠損: ${sc.missing.map((m) => m.value).join(', ')}`,
      })
    } else {
      chips.push({ label: '保全チェック', status: 'failed', detail: '失敗' })
    }
  }

  // Critic v1
  if (s.critic) {
    if (s.critic.status === 'completed' && s.critic.result) {
      const r = s.critic.result
      const status: Status =
        r.verdict === 'accept' ? 'completed' :
        r.verdict === 'reject' ? 'failed' : 'warn'
      const w = r.weighted != null ? ` ${(r.weighted * 100).toFixed(0)}` : ''
      chips.push({
        label: 'Critic',
        status,
        detail: `${r.verdict}${w}`,
        hint: r.issues.slice(0, 3).map((i) => i.msg).join(' / '),
      })
    } else {
      chips.push({ label: 'Critic', status: 'failed', detail: '失敗' })
    }
  }

  // リトライ開始
  if (s.pipelineStep?.step === 'retry_start') {
    chips.push({ label: 'リトライ', status: 'running', detail: 'v2 生成中' })
  }

  // Critic v2
  if (s.criticV2) {
    if (s.criticV2.status === 'completed' && s.criticV2.result) {
      const r = s.criticV2.result
      const status: Status =
        r.verdict === 'accept' ? 'completed' :
        r.verdict === 'reject' ? 'failed' : 'warn'
      const w = r.weighted != null ? ` ${(r.weighted * 100).toFixed(0)}` : ''
      chips.push({ label: 'Critic v2', status, detail: `${r.verdict}${w}` })
    } else {
      chips.push({ label: 'Critic v2', status: 'failed', detail: '失敗' })
    }
  }

  // ペアワイズ比較
  if (s.pairwise) {
    if (s.pairwise.status === 'completed') {
      chips.push({
        label: 'ペアワイズ',
        status: 'completed',
        detail: `winner=${s.pairwise.winner}`,
        hint: s.pairwise.reasoning,
      })
    } else {
      chips.push({ label: 'ペアワイズ', status: 'failed', detail: '失敗' })
    }
  }

  // ロールバック
  if (s.rollback) {
    chips.push({
      label: 'ロールバック',
      status: 'warn',
      detail: 'v1 を採用',
      hint: s.rollback.reason,
    })
  }

  return chips
}
