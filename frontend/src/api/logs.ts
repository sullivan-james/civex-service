import { api } from './client'

/** A log civex keeps on this computer (`GET /logs`). */
export interface LogSource {
  id: string
  name: string
  /** What writes it. */
  about: string
  path: string
  exists: boolean
  size: number | null
  modified: string | null
}

export interface LogLine {
  time: string | null
  /** debug, info, warning, error or critical, when the line says. */
  level: string | null
  message: string
  /** A structured line's other fields (logger, request id, ...). */
  fields: Record<string, unknown>
}

export interface LogRead {
  source: LogSource
  lines: LogLine[]
}

export interface LogQuery {
  lines?: number
  level?: string
  q?: string
}

export const logsApi = {
  list: () => api.get<LogSource[]>('/logs'),
  read: (id: string, { lines = 500, level, q }: LogQuery = {}) => {
    const p = new URLSearchParams({ lines: String(lines) })
    if (level) p.set('level', level)
    if (q) p.set('q', q)
    return api.get<LogRead>(`/logs/${encodeURIComponent(id)}?${p}`)
  },
  downloadUrl: (id: string) => `/api/logs/${encodeURIComponent(id)}/download`,
  /** Show the log's folder in the file manager (from this computer only). */
  open: (id: string) =>
    api.post<{ opened: boolean }>(`/logs/${encodeURIComponent(id)}/open`, {}),
}

/** The Logs page, at one log (and filter): where every "see the log" goes. */
export function logHref(id: string, level?: string): string {
  const p = new URLSearchParams({ log: id })
  if (level) p.set('level', level)
  return `/settings/logs?${p}`
}
