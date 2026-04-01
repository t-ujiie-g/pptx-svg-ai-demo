import { useState } from 'react'
import { ToolUsage } from '../services/chatHistory'

export function CollapsibleToolHistory({ toolUsages }: { toolUsages: ToolUsage[] }) {
  const [isExpanded, setIsExpanded] = useState(false)

  if (toolUsages.length === 0) return null

  return (
    <div className="tool-history-collapsible">
      <button
        className="tool-history-toggle"
        onClick={() => setIsExpanded(!isExpanded)}
        aria-expanded={isExpanded}
      >
        <span className="toggle-icon">
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            style={{ transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)' }}
          >
            <path d="M9 18l6-6-6-6" />
          </svg>
        </span>
        <span className="toggle-label">{toolUsages.length}件のツールを使用</span>
      </button>
      {isExpanded && (
        <div className="tool-history collapsed">
          {toolUsages.map((tool) => (
            <div key={tool.id} className="tool-status completed">
              <span className="tool-icon">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M20 6L9 17l-5-5" />
                </svg>
              </span>
              <span className="tool-name">{tool.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
