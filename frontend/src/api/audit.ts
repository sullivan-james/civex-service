import { setTableQuery, type TableQueryParams } from './query'

export interface AuditLogEntry {
  id: string
  commit_id: string | null
  action: string
  entity_type: string
  entity_id: string
  old_data: Record<string, unknown> | null
  new_data: Record<string, unknown> | null
  timestamp: string
}

export interface PaginatedAuditLog {
  items: AuditLogEntry[]
  total: number
  offset: number
  limit: number
}

/** `<base>/audit` with paging and the table's filter, sort and search --
 * every entity's history is fetched through this. */
export function auditUrl(
  base: string,
  offset: number,
  limit: number,
  table?: TableQueryParams,
): string {
  const qs = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  })
  if (table) setTableQuery(qs, table)
  return `${base}/audit?${qs}`
}
