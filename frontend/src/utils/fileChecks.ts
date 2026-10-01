import { formatBytes } from './restrictions'

/**
 * Pre-save checks for a file about to be attached to a field, mirroring the
 * `accept` / `max_size` rules in `_check_restrictions()` (record_service.py).
 * The server enforces them again when the record is saved; running them
 * early lets a staged upload say what is wrong before anyone approves it.
 */

/** Why `name` (of MIME type `mime`) doesn't match an `accept` list such as
 * ".csv,.txt" or "audio/*,.flac", or null if it does or there is no list. */
export function acceptProblem(
  name: string,
  mime: string,
  accept: string | undefined,
): string | null {
  const tokens = (accept ?? '')
    .split(',')
    .map((t) => t.trim().toLowerCase())
    .filter(Boolean)
  if (!tokens.length) return null
  const lower = name.toLowerCase()
  const type = mime.toLowerCase()
  const ok = tokens.some((t) => {
    if (t.startsWith('.')) return lower.endsWith(t)
    if (t.endsWith('/*')) return type.startsWith(t.slice(0, -1))
    return type === t
  })
  return ok ? null : `Type not accepted here (accepted: ${accept})`
}

export function sizeProblem(
  size: number,
  maxSize: number | undefined,
): string | null {
  return maxSize !== undefined && size > maxSize
    ? `Too large, max ${formatBytes(maxSize)}`
    : null
}
