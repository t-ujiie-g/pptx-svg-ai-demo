import { useState } from 'react'
import { ChatSession } from '../services/chatHistory'
import { SavedPrompt } from '../services/savedPrompts'
import { TemplateEditorData } from '../components/TemplateEditorModal'
import { config } from '../config'

export function useTemplateGeneration(session: ChatSession | null, isLoading: boolean) {
  const [isGeneratingTemplate, setIsGeneratingTemplate] = useState(false)
  const [showTemplateConfirm, setShowTemplateConfirm] = useState(false)
  const [templateEditorData, setTemplateEditorData] = useState<TemplateEditorData | null>(null)
  const [templateEditId, setTemplateEditId] = useState<string | undefined>(undefined)
  const [templateExecuteTarget, setTemplateExecuteTarget] = useState<SavedPrompt | null>(null)

  const openSaveModal = (content: string) => {
    setTemplateEditId(undefined)
    setTemplateEditorData({ name: '', content, variables: [], summary: '' })
  }

  const openEditModal = (prompt: SavedPrompt) => {
    setTemplateEditId(prompt.id)
    setTemplateEditorData({
      name: prompt.name,
      content: prompt.content,
      variables: prompt.variables ?? [],
      summary: '',
    })
  }

  const generateTemplate = async () => {
    if (!session || session.messages.length < 2 || isGeneratingTemplate || isLoading) return
    setIsGeneratingTemplate(true)
    try {
      const messagesWithFiles = session.messages.map((m) => {
        let content = m.content
        if (m.attachments && m.attachments.length > 0) {
          const fileInfo = m.attachments.map((a) => `${a.name} (${a.type})`).join(', ')
          content += `\n[添付ファイル: ${fileInfo}]`
        }
        return { role: m.role, content }
      })

      const response = await fetch(
        `${config.api.baseUrl}${config.api.endpoints.generateTemplate}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ messages: messagesWithFiles }),
        }
      )
      if (!response.ok) throw new Error(`HTTP error: ${response.status}`)
      const data = await response.json()
      setTemplateEditId(undefined)
      setTemplateEditorData({
        name: data.name,
        content: data.content,
        variables: (data.variables || []).map((v: {
          name: string; label: string; description: string; default_value: string; type?: string
        }) => ({
          name: v.name,
          label: v.label,
          description: v.description,
          defaultValue: v.default_value,
          ...(v.type === 'file' ? { type: 'file' as const } : {}),
        })),
        summary: data.summary || '',
      })
    } catch (error) {
      alert(`テンプレート生成に失敗しました: ${error}`)
    } finally {
      setIsGeneratingTemplate(false)
    }
  }

  const handleTemplateExecute = (
    resolvedContent: string,
    files: File[] | undefined,
    setInput: (v: string) => void,
    addFiles: (files: File[]) => void,
  ) => {
    setTemplateExecuteTarget(null)
    setInput(resolvedContent)
    if (files && files.length > 0) addFiles(files)
  }

  const closeTemplateEditor = () => {
    setTemplateEditorData(null)
    setTemplateEditId(undefined)
  }

  return {
    isGeneratingTemplate,
    showTemplateConfirm,
    setShowTemplateConfirm,
    templateEditorData,
    setTemplateEditorData,
    templateEditId,
    setTemplateEditId,
    templateExecuteTarget,
    setTemplateExecuteTarget,
    openSaveModal,
    openEditModal,
    generateTemplate,
    handleTemplateExecute,
    closeTemplateEditor,
  }
}
