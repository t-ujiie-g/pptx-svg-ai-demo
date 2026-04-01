import { formatFileSize, getFileIcon } from '../hooks/useFileAttachment'

interface FilePreviewAreaProps {
  files: File[]
  onRemove: (index: number) => void
  getPreviewUrl: (file: File) => string | undefined
}

export function FilePreviewArea({ files, onRemove, getPreviewUrl }: FilePreviewAreaProps) {
  if (files.length === 0) return null

  return (
    <div className="file-preview-area">
      {files.map((file, idx) => (
        <div key={idx} className="file-preview-item">
          {file.type.startsWith('image/') ? (
            <img
              className="file-preview-thumb"
              src={getPreviewUrl(file)}
              alt={file.name}
              onLoad={(e) => URL.revokeObjectURL((e.target as HTMLImageElement).src)}
            />
          ) : (
            <span className="file-preview-icon">{getFileIcon(file.type)}</span>
          )}
          <div className="file-preview-info">
            <span className="file-preview-name">{file.name}</span>
            <span className="file-preview-size">{formatFileSize(file.size)}</span>
          </div>
          <button
            className="file-preview-remove"
            onClick={() => onRemove(idx)}
            aria-label={`${file.name}を削除`}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
      ))}
    </div>
  )
}
