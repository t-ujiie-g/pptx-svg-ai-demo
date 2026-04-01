import { useState, useEffect } from 'react'
import { Sidebar } from './Sidebar'
import { ChatView } from './ChatView'
import { PptxPanel } from './PptxPanel'
import { chatHistoryService, ChatSession, PptxArtifactData } from '../services/chatHistory'
import { useTheme } from '../hooks/useTheme'
import './ChatLayout.css'

export function ChatLayout() {
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [currentSession, setCurrentSession] = useState<ChatSession | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [activePptxArtifact, setActivePptxArtifact] = useState<PptxArtifactData | null>(null)
  const [pptxMaximized, setPptxMaximized] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const { theme, setTheme } = useTheme()

  useEffect(() => {
    const init = async () => {
      const allSessions = await chatHistoryService.getAllSessions()
      setSessions(allSessions)
      if (allSessions.length > 0) {
        setCurrentSession(allSessions[0])
      }
      setIsLoading(false)
    }
    init()
  }, [])

  const handleNewChat = async () => {
    const newSession = await chatHistoryService.createSession()
    setSessions((prev) => [newSession, ...prev])
    setCurrentSession(newSession)
    setActivePptxArtifact(null)
    setPptxMaximized(false)
  }

  const handleSelectSession = async (id: string) => {
    const session = await chatHistoryService.getSession(id)
    if (session) {
      setCurrentSession(session)
      setActivePptxArtifact(null)
      setPptxMaximized(false)
    }
  }

  const handleDeleteSession = async (id: string) => {
    await chatHistoryService.deleteSession(id)
    setSessions((prev) => prev.filter((s) => s.id !== id))
    if (currentSession?.id === id) {
      const remaining = sessions.filter((s) => s.id !== id)
      setCurrentSession(remaining.length > 0 ? remaining[0] : null)
    }
  }

  const handleUpdateSession = async (session: ChatSession) => {
    await chatHistoryService.saveSession(session)
    setSessions((prev) => {
      const updated = prev.map((s) => (s.id === session.id ? session : s))
      return updated.sort((a, b) => b.updatedAt - a.updatedAt)
    })
    setCurrentSession(session)
  }

  const handleClosePptx = () => {
    setActivePptxArtifact(null)
    setPptxMaximized(false)
  }

  if (isLoading) {
    return (
      <div className="chat-layout loading">
        <div className="loading-spinner"></div>
      </div>
    )
  }

  const showPptx = !!activePptxArtifact
  const sidePanelClass = showPptx
    ? pptxMaximized ? 'with-slides slides-maximized' : 'with-slides'
    : ''

  return (
    <div className="chat-layout">
      <Sidebar
        sessions={sessions}
        currentSessionId={currentSession?.id || null}
        isOpen={sidebarOpen}
        theme={theme}
        onNewChat={handleNewChat}
        onSelectSession={handleSelectSession}
        onDeleteSession={handleDeleteSession}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
        onThemeChange={setTheme}
      />
      <main className={`chat-main ${sidebarOpen ? '' : 'sidebar-closed'}`}>
        <button
          className="sidebar-toggle"
          onClick={() => setSidebarOpen(!sidebarOpen)}
          aria-label="Toggle sidebar"
        >
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 12h18M3 6h18M3 18h18" />
          </svg>
        </button>
        <div className={`chat-main-content ${sidePanelClass}`}>
          <div className="chat-area">
            <ChatView
              session={currentSession}
              onUpdateSession={handleUpdateSession}
              onNewChat={handleNewChat}
              onPptxArtifactChange={setActivePptxArtifact}
            />
          </div>
          {showPptx && (
            <PptxPanel
              artifact={activePptxArtifact!}
              maximized={pptxMaximized}
              onToggleMaximize={() => setPptxMaximized((v) => !v)}
              onClose={handleClosePptx}
            />
          )}
        </div>
      </main>
    </div>
  )
}
