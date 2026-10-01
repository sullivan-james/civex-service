/**
 * File-type presets for a field's `accept` rule. The stored value stays the
 * plain comma-separated list the server checks (".gpx,.geojson", "audio/*");
 * presets are only how the editor lets people build and read it.
 */

export interface AcceptPreset {
  key: string
  label: string
  tokens: string[]
}

export const ACCEPT_PRESETS: AcceptPreset[] = [
  { key: 'image', label: 'Images', tokens: ['image/*'] },
  { key: 'audio', label: 'Audio', tokens: ['audio/*'] },
  { key: 'video', label: 'Video', tokens: ['video/*'] },
  { key: 'track', label: 'Tracks', tokens: ['.gpx', '.geojson', '.parquet'] },
  { key: 'table', label: 'Tables', tokens: ['.csv', '.tsv', '.parquet'] },
  { key: 'pdf', label: 'PDF', tokens: ['application/pdf'] },
]

function tokensOf(accept: string): string[] {
  return accept
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean)
}

/** Which presets an accept string includes, and what is left over. */
export function parseAccept(accept: string): {
  presets: string[]
  custom: string
} {
  const have = new Set(tokensOf(accept).map((t) => t.toLowerCase()))
  const presets = ACCEPT_PRESETS.filter((p) =>
    p.tokens.every((t) => have.has(t)),
  )
  const covered = new Set(presets.flatMap((p) => p.tokens))
  const custom = tokensOf(accept).filter((t) => !covered.has(t.toLowerCase()))
  return { presets: presets.map((p) => p.key), custom: custom.join(', ') }
}

/** The accept string for chosen presets plus extra extensions; '' if none. */
export function buildAccept(presets: string[], custom: string): string {
  const tokens: string[] = []
  for (const p of ACCEPT_PRESETS)
    if (presets.includes(p.key)) tokens.push(...p.tokens)
  for (const t of tokensOf(custom.replace(/\s+/g, ',')))
    tokens.push(t.startsWith('.') || t.includes('/') ? t : `.${t}`)
  return [...new Set(tokens)].join(',')
}
