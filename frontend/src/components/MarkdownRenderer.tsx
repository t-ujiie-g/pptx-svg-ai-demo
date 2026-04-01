import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { config } from '../config'
import './MarkdownRenderer.css'

interface MarkdownRendererProps {
  content: string
}

/**
 * Resolve backend API paths (e.g. /browser/sessions/...) to full URLs.
 * In production the API base URL differs from the frontend origin,
 * so relative paths must be prefixed with the backend base URL.
 */
function resolveHref(href: string | undefined): string | undefined {
  if (href && href.startsWith('/browser/')) {
    return `${config.api.baseUrl}${href}`
  }
  return href
}

export function MarkdownRenderer({ content }: MarkdownRendererProps) {
  return (
    <ReactMarkdown
      className="markdown-content"
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeHighlight]}
      components={{
        // Custom code block with copy button
        pre({ children, ...props }) {
          return (
            <div className="code-block-wrapper">
              <pre {...props}>{children}</pre>
            </div>
          )
        },
        // Custom link to open in new tab
        a({ href, children, ...props }) {
          const resolvedHref = resolveHref(href)
          return (
            <a href={resolvedHref} target="_blank" rel="noopener noreferrer" {...props}>
              {children}
            </a>
          )
        },
      }}
    >
      {content}
    </ReactMarkdown>
  )
}
