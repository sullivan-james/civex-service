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

/** What a history table can ask for: one kind of action, and an order
 * (`timestamp` or `action`, then `:asc` / `:desc`). */
export interface AuditView {
  action?: string
  sort?: string
}

/** `<base>/audit` with paging and the view, for every entity's history. */
export function auditUrl(
  base: string,
  offset: number,
  limit: number,
  view?: AuditView,
): string {
  const qs = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  })
  if (view?.action) qs.set('action', view.action)
  if (view?.sort) qs.set('sort', view.sort)
  return `${base}/audit?${qs}`
}
