export function pluralise(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? '' : 's'}`
}

export function formatDate(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffSec = Math.floor(diffMs / 1000)
  const diffMin = Math.floor(diffSec / 60)
  const diffHr  = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHr  / 24)

  if (diffSec < 60)  return 'just now'
  if (diffMin < 60)  return `${diffMin}m ago`
  if (diffHr  < 24)  return `${diffHr}h ago`
  if (diffDay < 7)   return `${diffDay}d ago`
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}
