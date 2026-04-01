import { useState, useRef, useEffect } from 'react'
import { ChatSession } from '../services/chatHistory'
import { config, Theme } from '../config'
import './Sidebar.css'

interface SidebarProps {
  sessions: ChatSession[]
  currentSessionId: string | null
  isOpen: boolean
  theme: Theme
  onNewChat: () => void
  onSelectSession: (id: string) => void
  onDeleteSession: (id: string) => void
  onToggle: () => void
  onThemeChange: (theme: Theme) => void
}

export function Sidebar({
  sessions,
  currentSessionId,
  isOpen,
  theme,
  onNewChat,
  onSelectSession,
  onDeleteSession,
  onToggle,
  onThemeChange,
}: SidebarProps) {
  const [themeMenuOpen, setThemeMenuOpen] = useState(false)
  const themeMenuRef = useRef<HTMLDivElement>(null)

  // Close menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (themeMenuRef.current && !themeMenuRef.current.contains(event.target as Node)) {
        setThemeMenuOpen(false)
      }
    }

    if (themeMenuOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [themeMenuOpen])
  const formatDate = (timestamp: number) => {
    const date = new Date(timestamp)
    const now = new Date()
    const diffDays = Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24))

    if (diffDays === 0) return '今日'
    if (diffDays === 1) return '昨日'
    if (diffDays < 7) return `${diffDays}日前`
    return date.toLocaleDateString('ja-JP', { month: 'short', day: 'numeric' })
  }

  const groupedSessions = sessions.reduce(
    (groups, session) => {
      const date = formatDate(session.updatedAt)
      if (!groups[date]) groups[date] = []
      groups[date].push(session)
      return groups
    },
    {} as Record<string, ChatSession[]>
  )

  const handleThemeSelect = (selectedTheme: Theme) => {
    onThemeChange(selectedTheme)
    setThemeMenuOpen(false)
  }

  const getThemeIcon = (themeType?: Theme) => {
    const t = themeType ?? theme
    switch (t) {
      case 'light':
        return (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="5" />
            <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
          </svg>
        )
      case 'dark':
        return (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" />
          </svg>
        )
      default:
        return (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
            <line x1="8" y1="21" x2="16" y2="21" />
            <line x1="12" y1="17" x2="12" y2="21" />
          </svg>
        )
    }
  }

  const getThemeLabel = () => {
    switch (theme) {
      case 'light': return 'ライト'
      case 'dark': return 'ダーク'
      default: return 'システム'
    }
  }

  return (
    <aside className={`sidebar ${isOpen ? 'open' : 'closed'}`}>
      <div className="sidebar-header">
        <button className="new-chat-btn" onClick={onNewChat}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 5v14M5 12h14" />
          </svg>
          新しいチャット
        </button>
        <button className="sidebar-close" onClick={onToggle} aria-label="Close sidebar">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
      </div>

      <nav className="sidebar-nav">
        {Object.entries(groupedSessions).map(([date, dateSessions]) => (
          <div key={date} className="session-group">
            <div className="session-group-title">{date}</div>
            {dateSessions.map((session) => (
              <div
                key={session.id}
                className={`session-item ${session.id === currentSessionId ? 'active' : ''}`}
                onClick={() => onSelectSession(session.id)}
              >
                <span className="session-title">{session.title}</span>
                <button
                  className="session-delete"
                  onClick={(e) => {
                    e.stopPropagation()
                    onDeleteSession(session.id)
                  }}
                  aria-label="Delete chat"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        ))}

        {sessions.length === 0 && (
          <div className="empty-state">
            <p>チャット履歴がありません</p>
          </div>
        )}
      </nav>

      <div className="sidebar-footer">
        <div className="theme-selector" ref={themeMenuRef}>
          <button
            className="theme-toggle"
            onClick={() => setThemeMenuOpen(!themeMenuOpen)}
            aria-expanded={themeMenuOpen}
            aria-haspopup="true"
          >
            {getThemeIcon()}
            <span>{getThemeLabel()}</span>
            <svg
              className={`theme-toggle-arrow ${themeMenuOpen ? 'open' : ''}`}
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>
          {themeMenuOpen && (
            <div className="theme-menu">
              <button
                className={`theme-menu-item ${theme === 'system' ? 'active' : ''}`}
                onClick={() => handleThemeSelect('system')}
              >
                {getThemeIcon('system')}
                <span>システム</span>
                {theme === 'system' && (
                  <svg className="check-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M20 6L9 17l-5-5" />
                  </svg>
                )}
              </button>
              <button
                className={`theme-menu-item ${theme === 'light' ? 'active' : ''}`}
                onClick={() => handleThemeSelect('light')}
              >
                {getThemeIcon('light')}
                <span>ライト</span>
                {theme === 'light' && (
                  <svg className="check-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M20 6L9 17l-5-5" />
                  </svg>
                )}
              </button>
              <button
                className={`theme-menu-item ${theme === 'dark' ? 'active' : ''}`}
                onClick={() => handleThemeSelect('dark')}
              >
                {getThemeIcon('dark')}
                <span>ダーク</span>
                {theme === 'dark' && (
                  <svg className="check-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M20 6L9 17l-5-5" />
                  </svg>
                )}
              </button>
            </div>
          )}
        </div>
        <div className="app-info">
          <span className="app-name">{config.app.name}</span>
          <span className="app-version">v{config.app.version}</span>
        </div>
      </div>
    </aside>
  )
}
