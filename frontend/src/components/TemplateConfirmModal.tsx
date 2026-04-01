interface TemplateConfirmModalProps {
  onConfirm: () => void
  onCancel: () => void
}

export function TemplateConfirmModal({ onConfirm, onCancel }: TemplateConfirmModalProps) {
  return (
    <div className="template-confirm-overlay" onClick={onCancel}>
      <div className="template-confirm-modal" onClick={(e) => e.stopPropagation()}>
        <div className="template-confirm-header">
          <h3>テンプレートを生成</h3>
          <button className="template-confirm-close" onClick={onCancel}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="template-confirm-body">
          <div className="template-confirm-icon">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z" />
            </svg>
          </div>
          <p className="template-confirm-description">
            この会話をAIが分析し、<strong>再利用可能なプロンプトテンプレート</strong>を自動生成します。
          </p>
          <ul className="template-confirm-steps">
            <li>会話の意図と成果物を分析</li>
            <li>変動する部分を変数に自動変換</li>
            <li>生成後にテンプレートの編集が可能</li>
          </ul>
        </div>
        <div className="template-confirm-footer">
          <button className="template-confirm-cancel" onClick={onCancel}>
            キャンセル
          </button>
          <button className="template-confirm-execute" onClick={onConfirm}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z" />
            </svg>
            生成する
          </button>
        </div>
      </div>
    </div>
  )
}
