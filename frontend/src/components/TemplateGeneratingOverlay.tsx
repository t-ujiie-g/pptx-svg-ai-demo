export function TemplateGeneratingOverlay() {
  return (
    <div className="template-generating-overlay">
      <div className="template-generating-card">
        <div className="template-generating-spinner">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z" />
          </svg>
        </div>
        <p className="template-generating-text">テンプレートを生成しています...</p>
        <p className="template-generating-subtext">会話を分析して最適なテンプレートを作成中</p>
        <div className="template-generating-dots">
          <span></span><span></span><span></span>
        </div>
      </div>
    </div>
  )
}
