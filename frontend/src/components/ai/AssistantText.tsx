import CodeBlock from './CodeBlock'

// Splits assistant text on code fences so fenced blocks render via
// CodeBlock (with its own copy button) instead of as plain text.
export default function AssistantText({
  text,
  streaming,
}: {
  text: string
  streaming: boolean
}) {
  const parts: Array<{ type: 'text' | 'code'; lang: string; content: string }> =
    []
  const fenceRe = /```(\w*)\n([\s\S]*?)```/g
  let lastIndex = 0
  let m: RegExpExecArray | null

  while ((m = fenceRe.exec(text)) !== null) {
    if (m.index > lastIndex) {
      parts.push({
        type: 'text',
        lang: '',
        content: text.slice(lastIndex, m.index),
      })
    }
    parts.push({ type: 'code', lang: m[1] || 'text', content: m[2] })
    lastIndex = fenceRe.lastIndex
  }
  const trailing = text.slice(lastIndex)
  if (trailing) {
    parts.push({ type: 'text', lang: '', content: trailing })
  }

  return (
    <div className="text-sm text-fg">
      {parts.map((p, i) =>
        p.type === 'code' ? (
          <CodeBlock key={i} lang={p.lang} code={p.content} />
        ) : (
          <span key={i} className="whitespace-pre-wrap">
            {p.content}
          </span>
        ),
      )}
      {streaming && (
        <span className="inline-block w-1.5 h-3.5 bg-accent animate-pulse ml-1 align-middle" />
      )}
    </div>
  )
}
