import { useEffect, useRef, useState } from 'react'
import {
  listSessionArtifacts,
  getPptx as getPptxFromOpfs,
  type StoredArtifactMeta,
} from '../services/pptxStorage'
import { PptxArtifactData } from '../services/chatHistory'
import { config, downloadFromBlob } from '../config'
import './PptxHistoryDropdown.css'

interface Props {
  sessionId: string | null
  /** 現在表示中の artifact ID（ハイライト表示） */
  activeArtifactId?: string
  /** 履歴の項目をクリックしたとき: その artifact をプレビューに切り替える */
  onSelect: (artifact: PptxArtifactData) => void
}

function formatRelativeTime(ms: number): string {
  const diff = Date.now() - ms
  const sec = Math.floor(diff / 1000)
  if (sec < 60) return 'たった今'
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}分前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}時間前`
  const day = Math.floor(hr / 24)
  return `${day}日前`
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/**
 * セッション内に OPFS で保存された PPTX 世代のドロップダウン履歴。
 * ヘッダの「履歴」ボタンを押すと展開し、各世代をクリックでプレビュー切替、
 * DL アイコンで保存。
 */
export function PptxHistoryDropdown({ sessionId, activeArtifactId, onSelect }: Props) {
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<StoredArtifactMeta[]>([])
  const containerRef = useRef<HTMLDivElement>(null)

  // 開いた時とセッション切替時にロード
  useEffect(() => {
    if (!open || !sessionId) return
    let cancelled = false
    listSessionArtifacts(sessionId).then((list) => {
      if (!cancelled) setItems(list)
    })
    return () => {
      cancelled = true
    }
  }, [open, sessionId, activeArtifactId])

  // 外側クリックで閉じる
  useEffect(() => {
    if (!open) return
    const onDocClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  if (!sessionId) return null

  const handleSelect = (item: StoredArtifactMeta) => {
    onSelect({
      artifactId: item.artifactId,
      filename: item.filename,
      sizeBytes: item.sizeBytes,
      // 既に backend にあれば直接 fetch、なければ Viewer の OPFS フォールバックが効く
      downloadUrl: `/artifacts/${item.artifactId}`,
    })
    setOpen(false)
  }

  const handleDownload = async (e: React.MouseEvent, item: StoredArtifactMeta) => {
    e.stopPropagation()
    // バックエンドが生きていればそこから、無ければ OPFS から DL
    try {
      const resp = await fetch(`${config.api.baseUrl}/artifacts/${item.artifactId}`)
      if (resp.ok) {
        const blob = await resp.blob()
        downloadFromBlob(blob, item.filename)
        return
      }
    } catch {
      /* fallthrough to OPFS */
    }
    const localBlob = await getPptxFromOpfs(sessionId, item.artifactId)
    if (localBlob) {
      downloadFromBlob(localBlob, item.filename)
    } else {
      console.warn(`[history] no source available for ${item.artifactId}`)
    }
  }

  return (
    <div className="pptx-history" ref={containerRef}>
      <button
        type="button"
        className="pptx-history__btn"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title="このチャットの履歴"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="9" />
          <polyline points="12 7 12 12 16 14" />
        </svg>
        <span className="pptx-history__btn-label">履歴</span>
        {items.length > 0 && (
          <span className="pptx-history__btn-count">{items.length}</span>
        )}
      </button>

      {open && (
        <div className="pptx-history__panel">
          {items.length === 0 ? (
            <div className="pptx-history__empty">このチャットの保存版はまだありません</div>
          ) : (
            <ul className="pptx-history__list">
              {items.map((item) => {
                const isActive = item.artifactId === activeArtifactId
                return (
                  <li
                    key={item.artifactId}
                    className={`pptx-history__item ${isActive ? 'pptx-history__item--active' : ''}`}
                    onClick={() => handleSelect(item)}
                  >
                    <div className="pptx-history__main">
                      <div className="pptx-history__filename">{item.filename}</div>
                      <div className="pptx-history__meta">
                        <span>{formatRelativeTime(item.savedAt)}</span>
                        <span>·</span>
                        <span>{formatSize(item.sizeBytes)}</span>
                      </div>
                    </div>
                    <button
                      type="button"
                      className="pptx-history__dl"
                      onClick={(e) => handleDownload(e, item)}
                      title="ダウンロード"
                      aria-label="この版をダウンロード"
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                        <polyline points="7 10 12 15 17 10" />
                        <line x1="12" y1="15" x2="12" y2="3" />
                      </svg>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

