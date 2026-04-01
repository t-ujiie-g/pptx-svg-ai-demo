import { useState, useCallback } from 'react'
import { FileAttachment } from '../services/chatHistory'

export const ALLOWED_MIME_TYPES = new Set([
  'image/png', 'image/jpeg', 'image/webp', 'image/heic', 'image/heif',
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'text/plain', 'text/html', 'text/csv',
  'audio/wav', 'audio/mp3', 'audio/mpeg', 'audio/ogg', 'audio/webm',
  'video/mp4', 'video/webm', 'video/mpeg',
])

export const ACCEPT_TYPES = Array.from(ALLOWED_MIME_TYPES).join(',')

const MAX_FILE_SIZE = 20 * 1024 * 1024 // 20MB

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function getFileIcon(mimeType: string): string {
  if (mimeType.startsWith('image/')) return '🖼'
  if (mimeType === 'application/pdf') return '📄'
  if (mimeType === 'application/vnd.openxmlformats-officedocument.presentationml.presentation') return '📊'
  if (mimeType.startsWith('text/')) return '📝'
  if (mimeType.startsWith('audio/')) return '🎵'
  if (mimeType.startsWith('video/')) return '🎬'
  return '📎'
}

export function useFileAttachment() {
  const [attachedFiles, setAttachedFiles] = useState<File[]>([])

  const validateFiles = useCallback((files: File[]): File[] => {
    const valid: File[] = []
    for (const file of files) {
      if (!ALLOWED_MIME_TYPES.has(file.type)) {
        alert(`サポートされていないファイル形式です: ${file.name} (${file.type || '不明'})`)
        continue
      }
      if (file.size > MAX_FILE_SIZE) {
        alert(`ファイルサイズが上限(${formatFileSize(MAX_FILE_SIZE)})を超えています: ${file.name} (${formatFileSize(file.size)})`)
        continue
      }
      valid.push(file)
    }
    return valid
  }, [])

  const addFiles = useCallback((files: File[]) => {
    const validated = validateFiles(files)
    if (validated.length > 0) {
      setAttachedFiles((prev) => [...prev, ...validated])
    }
  }, [validateFiles])

  const removeFile = useCallback((index: number) => {
    setAttachedFiles((prev) => prev.filter((_, i) => i !== index))
  }, [])

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      addFiles(Array.from(e.target.files))
      e.target.value = ''
    }
  }, [addFiles])

  const handlePaste = useCallback((e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData?.items
    if (!items) return
    const files: File[] = []
    for (const item of items) {
      if (item.kind === 'file') {
        const file = item.getAsFile()
        if (file) files.push(file)
      }
    }
    if (files.length > 0) {
      e.preventDefault()
      addFiles(files)
    }
  }, [addFiles])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.dataTransfer.files.length > 0) {
      addFiles(Array.from(e.dataTransfer.files))
    }
  }, [addFiles])

  const getPreviewUrl = useCallback((file: File): string | undefined => {
    if (file.type.startsWith('image/') && file.size <= 1024 * 1024) {
      return URL.createObjectURL(file)
    }
    return undefined
  }, [])

  const createAttachmentMeta = useCallback(async (files: File[]): Promise<FileAttachment[]> => {
    return Promise.all(
      files.map(async (file) => {
        let previewUrl: string | undefined
        if (file.type.startsWith('image/') && file.size <= 1024 * 1024) {
          previewUrl = await new Promise<string>((resolve) => {
            const reader = new FileReader()
            reader.onload = () => resolve(reader.result as string)
            reader.readAsDataURL(file)
          })
        }
        return { name: file.name, type: file.type, size: file.size, previewUrl }
      })
    )
  }, [])

  return {
    attachedFiles,
    setAttachedFiles,
    addFiles,
    removeFile,
    handleFileSelect,
    handlePaste,
    handleDragOver,
    handleDrop,
    getPreviewUrl,
    createAttachmentMeta,
  }
}
