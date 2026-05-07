/**
 * ModeSpec — PPTX生成の3スロットモデル (Phase 1)
 *
 * 1. Input    : target (pptxArtifactId) + style_ref (styleRefArtifactId)
 * 2. Intent   : target をどれくらい変えるか
 * 3. Style    : スタイルの取得元
 */

export type Intent = 'tweak' | 'polish' | 'restructure' | 'from-scratch'

export type StyleSourceKind = 'from-target' | 'from-ref' | 'preset' | 'mix'

export type StylePreset = 'best-practice' | 'bold' | 'dense' | 'minimal'

export interface StyleSource {
  kind: StyleSourceKind
  /** kind が "preset" or "mix" の場合は必須 */
  preset?: StylePreset
  /** kind が "mix" の場合に意味を持つ。0..1。1=refメイン / 0=presetメイン */
  ref_weight?: number
}

export interface ModeSpec {
  intent: Intent
  style_source: StyleSource
  /** バックエンドで自動推定されたか */
  auto_inferred: boolean
  /** ユーザーが推定値を上書きしたか */
  user_overridden: boolean
}

export const INTENT_LABELS: Record<Intent, string> = {
  tweak: '微修正',
  polish: '整形',
  restructure: '作り直し',
  'from-scratch': '新規作成',
}

export const STYLE_SOURCE_KIND_LABELS: Record<StyleSourceKind, string> = {
  'from-target': '対象を踏襲',
  'from-ref': '参照スタイル',
  preset: 'プリセット',
  mix: '参照+プリセット',
}

export const STYLE_PRESET_LABELS: Record<StylePreset, string> = {
  'best-practice': 'ベストプラクティス',
  bold: '派手',
  dense: '情報密度高',
  minimal: 'ミニマル',
}

/** intent ∈ {tweak, polish} は target が必要 */
export function intentRequiresTarget(intent: Intent): boolean {
  return intent === 'tweak' || intent === 'polish'
}

/** style_source.kind == 'from-ref' は style_ref が必要 */
export function styleSourceRequiresRef(kind: StyleSourceKind): boolean {
  return kind === 'from-ref'
}

/**
 * クライアント側 mode 推定ロジック。
 *
 * ⚠️ 同一ロジックがバックエンドの `backend/src/agents/mode/inferrer.py` にも実装
 * されています。ルール変更時は両方更新してください（送信前のUIプレビューと
 * バックエンド最終確定の挙動が一致しないとモードが揺れます）。
 */
const RESTRUCTURE_PATTERNS = [
  /作り直/, /リデザイン/, /ガラッと/, /ゼロから/, /全面的に/, /一新/, /刷新/,
]
const POLISH_PATTERNS = [
  /整えて/, /きれい/, /綺麗/, /体裁/, /見やすく/, /清書/, /レイアウトを/,
]

export function inferModeSpec(args: {
  text: string
  hasTarget: boolean
  hasStyleRef: boolean
}): ModeSpec {
  const { text, hasTarget, hasStyleRef } = args
  let intent: Intent
  let style_source: StyleSource

  if (!hasTarget) {
    intent = 'from-scratch'
    style_source = hasStyleRef
      ? { kind: 'from-ref' }
      : { kind: 'preset', preset: 'best-practice' }
  } else {
    if (RESTRUCTURE_PATTERNS.some((re) => re.test(text))) {
      intent = 'restructure'
    } else if (POLISH_PATTERNS.some((re) => re.test(text))) {
      intent = 'polish'
    } else {
      // 残りは tweak。文字数だけで restructure に倒すと誤爆するため保守的に倒す。
      intent = 'tweak'
    }
    style_source = hasStyleRef ? { kind: 'from-ref' } : { kind: 'from-target' }
  }

  return {
    intent,
    style_source,
    auto_inferred: true,
    user_overridden: false,
  }
}
