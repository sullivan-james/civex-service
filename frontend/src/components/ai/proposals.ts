import type { ApprovalResolution, ToolCallEntry } from '../../types/ai'

// Mutating "act" tools follow the propose → user-approves-in-UI → REST flow.
export const ACT_TOOL_NAMES = new Set([
  'create_record',
  'update_record',
  'delete_record',
  'create_schema',
  'update_schema',
  'delete_schema',
  'add_schema_field',
  'update_schema_field',
  'delete_schema_field',
  'create_collection',
  'update_collection',
  'delete_collection',
])

export const isSaveToolName = (name: string) =>
  name === 'save_workflow' || name === 'save_plugin'

interface ActRequest {
  method: string
  path: string
  body?: unknown
}
interface Proposal {
  status?: string
  summary?: string
  destructive?: boolean
  request?: ActRequest
  preview?: unknown
  content?: string
  code?: string
  message?: string
}

export function parseResult(result: string | null): Proposal | null {
  if (!result) return null
  try {
    return JSON.parse(result) as Proposal
  } catch {
    return null
  }
}

// A tool call that has proposed a change the user hasn't yet resolved.
export function isPendingApproval(entry: ToolCallEntry): boolean {
  if (entry.outcome) return false
  return parseResult(entry.result)?.status === 'proposed'
}

async function apiSend(
  path: string,
  method: string,
  body?: unknown,
): Promise<void> {
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as Record<string, unknown>
    throw new Error((err.detail as string) ?? `HTTP ${res.status}`)
  }
}

// Applies one resolved proposal. Pure — no component state — so both the
// per-card Approve button and the bulk "Approve all" action share one code
// path instead of drifting out of sync.
export async function applyProposal(
  entry: ToolCallEntry,
  stem?: string,
): Promise<ApprovalResolution> {
  const parsed = parseResult(entry.result)
  if (entry.name === 'save_workflow') {
    await apiSend(`/api/workflows/${encodeURIComponent(stem ?? '')}`, 'PUT', {
      content: parsed?.content,
    })
    return { outcome: 'approved', outcomeLabel: `${stem}.yaml` }
  }
  if (entry.name === 'save_plugin') {
    await apiSend('/api/plugins', 'POST', { name: stem, code: parsed?.code })
    return { outcome: 'approved', outcomeLabel: `${stem}.py` }
  }
  if (parsed?.request) {
    await apiSend(
      parsed.request.path,
      parsed.request.method,
      parsed.request.body,
    )
    return {
      outcome: 'approved',
      outcomeLabel: parsed.summary ?? 'Change applied',
    }
  }
  throw new Error(
    'This proposal is missing its request details and cannot be applied.',
  )
}

// A proposal is safe to fold into "Approve all": not destructive, not a
// save_* tool (those need a filename decision first), and has a fully
// formed request.
export function isBulkable(entry: ToolCallEntry): boolean {
  const parsed = parseResult(entry.result)
  return (
    !isSaveToolName(entry.name) &&
    !parsed?.destructive &&
    Boolean(parsed?.request)
  )
}
