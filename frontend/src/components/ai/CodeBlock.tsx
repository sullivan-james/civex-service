import { useState } from 'react'
import { Check } from '../ui/icons'

export default function CodeBlock({
  lang,
  code,
}: {
  lang: string
  code: string
}) {
  const [copied, setCopied] = useState(false)
  function copy() {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <div className="relative my-2 rounded-md border border-border bg-canvas-subtle text-xs font-mono overflow-x-auto">
      <div className="flex items-center justify-between px-3 py-1 border-b border-border bg-border-muted">
        <span className="text-fg-muted">{lang}</span>
        <button
          onClick={copy}
          className="inline-flex items-center gap-1 text-fg-muted hover:text-fg transition-colors"
        >
          {copied ? (
            <>
              <Check size={12} /> Copied
            </>
          ) : (
            'Copy'
          )}
        </button>
      </div>
      <pre className="p-3 whitespace-pre-wrap break-words">{code}</pre>
    </div>
  )
}
