import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

// Renders assistant text / artifact bodies. Links open in a new tab.
export default function Markdown({ children, className = '' }: { children: string; className?: string }) {
  return (
    <div className={`md ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ node, ...props }) => <a {...props} target="_blank" rel="noreferrer noopener" />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
