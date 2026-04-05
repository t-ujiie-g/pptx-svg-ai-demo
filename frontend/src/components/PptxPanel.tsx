import { forwardRef } from 'react'
import { PptxArtifactData } from '../services/chatHistory'
import { PptxSlideViewer, type PptxSlideViewerHandle } from './PptxSlideViewer'
import { downloadFromApi } from '../config'
import './PptxPanel.css'

interface PptxPanelProps {
  artifact: PptxArtifactData
  maximized: boolean
  onToggleMaximize: () => void
  onClose: () => void
}

export const PptxPanel = forwardRef<PptxSlideViewerHandle, PptxPanelProps>(
  function PptxPanel({ artifact, maximized, onToggleMaximize, onClose }, ref) {
    const handleDownload = () => downloadFromApi(artifact.downloadUrl, artifact.filename)

    return (
      <div className="pptx-panel">
        <div className="pptx-panel-header">
          <div className="pptx-panel-title">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z" />
              <polyline points="13 2 13 9 20 9" />
            </svg>
            <span>{artifact.filename}</span>
          </div>
          <div className="pptx-panel-actions">
            <button
              className="pptx-panel-action-btn"
              onClick={handleDownload}
              title="ダウンロード"
              aria-label="ダウンロード"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
            </button>
            <button
              className={`pptx-panel-action-btn ${maximized ? 'active' : ''}`}
              onClick={onToggleMaximize}
              title={maximized ? '元に戻す' : '最大化'}
              aria-label={maximized ? '元に戻す' : '最大化'}
            >
              {maximized ? (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polyline points="4 14 10 14 10 20" />
                  <polyline points="20 10 14 10 14 4" />
                  <line x1="14" y1="10" x2="21" y2="3" />
                  <line x1="3" y1="21" x2="10" y2="14" />
                </svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polyline points="15 3 21 3 21 9" />
                  <polyline points="9 21 3 21 3 15" />
                  <line x1="21" y1="3" x2="14" y2="10" />
                  <line x1="3" y1="21" x2="10" y2="14" />
                </svg>
              )}
            </button>
            <button className="pptx-panel-action-btn" onClick={onClose} aria-label="スライドパネルを閉じる">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M18 6L6 18M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>
        <div className="pptx-panel-body">
          <PptxSlideViewer
            ref={ref}
            artifactId={artifact.artifactId}
            filename={artifact.filename}
            downloadUrl={artifact.downloadUrl}
            showHeader={false}
          />
        </div>
      </div>
    )
  },
)
