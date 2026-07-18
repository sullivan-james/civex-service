import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  type AiConfig,
  type AiEvent,
  type ChatMessage,
  type OllamaModel,
  type OpenRouterLimits,
  PRESET_PROVIDERS,
  type PresetProviderId,
  getAiConfig,
  getOllamaModels,
  getOpenRouterAuthUrl,
  getOpenRouterLimits,
  streamChat,
  updateAiConfig,
} from '../../api/ai'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type UserEntry = { kind: 'user'; text: string }
type AssistantEntry = { kind: 'assistant'; text: string; streaming: boolean }
type ToolCallEntry = {
  kind: 'tool_call'
  id: string
  name: string
  input: Record<string, unknown>
  result: string | null
  // Set once the user resolves a proposed change. Persisted so the approval
  // prompt does not reappear after a reload.
  outcome?: 'approved' | 'cancelled' | 'error'
  outcomeLabel?: string
}
type ChatEntry = UserEntry | AssistantEntry | ToolCallEntry

interface StoredSession {
  id: string
  title: string
  createdAt: string
  entries: ChatEntry[]
}

// ---------------------------------------------------------------------------
// Session persistence helpers
// ---------------------------------------------------------------------------

const SESSIONS_KEY = 'civex-ai-sessions'
const MAX_SESSIONS = 15

function loadSessions(): StoredSession[] {
  try {
    return JSON.parse(localStorage.getItem(SESSIONS_KEY) ?? '[]')
  } catch {
    return []
  }
}

function saveSessions(sessions: StoredSession[]): void {
  try {
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions))
  } catch {
    /* quota exceeded */
  }
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return `${Math.floor(diff / 86_400_000)}d ago`
}

// ---------------------------------------------------------------------------
// Code block renderer
// ---------------------------------------------------------------------------

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false)
  function copy() {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <div className="relative my-2 rounded-md border border-[#d0d7de] bg-[#f6f8fa] text-xs font-mono overflow-x-auto">
      <div className="flex items-center justify-between px-3 py-1 border-b border-[#d0d7de] bg-[#eaeef2]">
        <span className="text-[#656d76]">{lang}</span>
        <button
          onClick={copy}
          className="text-[#656d76] hover:text-[#1f2328] transition-colors"
        >
          {copied ? '✓ Copied' : 'Copy'}
        </button>
      </div>
      <pre className="p-3 whitespace-pre-wrap break-words">{code}</pre>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Assistant message renderer — splits on code fences
// ---------------------------------------------------------------------------

function AssistantText({
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
    <div className="text-sm text-[#1f2328]">
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
        <span className="inline-block w-1.5 h-3.5 bg-[#0969da] animate-pulse ml-0.5 align-middle" />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tool call row
// ---------------------------------------------------------------------------

// Mutating "act" tools follow the propose → user-approves-in-UI → REST flow.
const ACT_TOOL_NAMES = new Set([
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

const isSaveToolName = (name: string) =>
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

function parseResult(result: string | null): Proposal | null {
  if (!result) return null
  try {
    return JSON.parse(result) as Proposal
  } catch {
    return null
  }
}

// A tool call that has proposed a change the user hasn't yet resolved.
function isPendingApproval(entry: ToolCallEntry): boolean {
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

interface ApprovalResolution {
  outcome: 'approved' | 'cancelled' | 'error'
  outcomeLabel?: string
}
type ResolvedEntry = { id: string } & ApprovalResolution

// What the model sees for a tool_call on later turns must reflect what
// actually happened, not the original "proposed" status forever -- otherwise
// it can never tell whether to build on an approved change, back off after a
// cancellation, or retry after an error. Layers the real outcome on top of
// the original result JSON.
function resultForApi(e: ToolCallEntry): string {
  if (!e.outcome) return e.result ?? ''
  try {
    const parsed = JSON.parse(e.result ?? '{}') as Record<string, unknown>
    if (e.outcome === 'approved') {
      return JSON.stringify({
        ...parsed,
        status: 'approved',
        note: e.outcomeLabel
          ? `Approved and applied: ${e.outcomeLabel}`
          : 'The user approved this change; it has been applied.',
      })
    }
    if (e.outcome === 'cancelled') {
      return JSON.stringify({
        ...parsed,
        status: 'cancelled',
        note: 'The user did not approve this change. Do not retry it unless asked again.',
      })
    }
    return JSON.stringify({
      ...parsed,
      status: 'error',
      message: e.outcomeLabel ?? 'Applying this change failed.',
    })
  } catch {
    return e.result ?? ''
  }
}

// Applies one resolved proposal. Pure — no component state — so both the
// per-card Approve button and the bulk "Approve all" action share one code
// path instead of drifting out of sync.
async function applyProposal(
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
function isBulkable(entry: ToolCallEntry): boolean {
  const parsed = parseResult(entry.result)
  return (
    !isSaveToolName(entry.name) &&
    !parsed?.destructive &&
    Boolean(parsed?.request)
  )
}

// ---------------------------------------------------------------------------
// Tool call row — display only. The approve/cancel action lives in ApprovalBar
// pinned above the input, so it is always the last thing shown (chronological).
// ---------------------------------------------------------------------------

function ToolCallRow({ entry }: { entry: ToolCallEntry }) {
  const isSaveTool = isSaveToolName(entry.name)
  const isActTool = ACT_TOOL_NAMES.has(entry.name)
  const [open, setOpen] = useState(isSaveTool || isActTool)
  const safeInput = entry.input ?? {}
  const parsed = parseResult(entry.result)
  const isToolError = parsed?.status === 'error'

  return (
    <div className="my-1 rounded border border-[#d0d7de] bg-[#f6f8fa] text-xs overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left text-[#656d76] hover:bg-[#eaeef2] transition-colors"
      >
        <span>⚙</span>
        <span className="font-mono">{entry.name}</span>
        <span className="ml-auto text-[#adbac7]">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="border-t border-[#d0d7de] p-3 space-y-2">
          {/* Content preview */}
          {entry.name === 'save_workflow' &&
          (parsed?.content ?? safeInput.content) ? (
            <CodeBlock
              lang="yaml"
              code={(parsed?.content ?? safeInput.content) as string}
            />
          ) : entry.name === 'save_plugin' &&
            (parsed?.code ?? safeInput.code) ? (
            <CodeBlock
              lang="python"
              code={(parsed?.code ?? safeInput.code) as string}
            />
          ) : isActTool ? (
            parsed?.preview ? (
              <pre className="text-[#656d76] whitespace-pre-wrap break-words">
                {JSON.stringify(parsed.preview, null, 2)}
              </pre>
            ) : null
          ) : !isSaveTool ? (
            <pre className="text-[#1f2328] whitespace-pre-wrap break-words">
              {JSON.stringify(entry.input, null, 2)}
            </pre>
          ) : null}

          {/* Resolved outcome (persisted, survives reload) */}
          {entry.outcome === 'approved' && (
            <div className="mt-2 rounded px-2 py-1 bg-[#dafbe1] text-[#1a7f37]">
              {entry.name === 'save_workflow' && (
                <Link to="/workflows" className="underline mr-2">
                  View in Workflows →
                </Link>
              )}
              ✓ {entry.outcomeLabel ?? 'Done'}
            </div>
          )}
          {entry.outcome === 'cancelled' && (
            <div className="mt-2 rounded px-2 py-1 bg-[#f6f8fa] text-[#adbac7] border border-[#d0d7de]">
              Cancelled
            </div>
          )}
          {entry.outcome === 'error' && (
            <div className="mt-2 rounded px-2 py-1 bg-[#ffebe9] text-[#d1242f]">
              {entry.outcomeLabel}
            </div>
          )}

          {/* Awaiting resolution — the buttons are in the bar below the messages */}
          {isPendingApproval(entry) && (
            <div className="mt-2 text-[#9a6700]">
              Awaiting your approval below ↓
            </div>
          )}

          {/* Validation error from the AI tool (status === 'error') */}
          {isToolError && (
            <div className="mt-2 rounded px-2 py-1 bg-[#ffebe9] text-[#d1242f]">
              {parsed?.message ?? entry.result}
            </div>
          )}

          {/* Read-only tool results (raw). Act/save tools render status above. */}
          {!isSaveTool && !isActTool && entry.result && (
            <div className="mt-2 text-[#656d76]">{entry.result}</div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Approval bar — pinned above the input while a proposal awaits the user.
// ---------------------------------------------------------------------------

// Rendered with `key={entry.id}` by the caller so each proposal gets a fresh
// component instance — otherwise React reuses the same instance across
// different proposals (same position in the tree) and stale `busy`/`stem`/
// `error` state bleeds from one approval into the next.
function ApprovalBar({
  entry,
  onResolve,
}: {
  entry: ToolCallEntry
  onResolve: (resolutions: ResolvedEntry[]) => void
}) {
  const parsed = parseResult(entry.result)
  const isSaveTool = isSaveToolName(entry.name)
  const destructive = Boolean(parsed?.destructive)
  const safeInput = entry.input ?? {}
  const [stem, setStem] = useState(
    (safeInput.stem ?? safeInput.name ?? '') as string,
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function approve() {
    setBusy(true)
    setError('')
    try {
      const result = await applyProposal(entry, stem)
      onResolve([{ id: entry.id, ...result }])
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const summary = isSaveTool
    ? entry.name === 'save_workflow'
      ? 'Save this workflow?'
      : 'Save this plugin?'
    : ((parsed?.summary as string) ?? 'Apply this change?')
  const approveLabel = destructive ? 'Delete' : isSaveTool ? 'Save' : 'Approve'

  return (
    <div
      className={`rounded-md border p-3 ${destructive ? 'bg-[#ffebe9] border-[#ff8182]' : 'bg-[#ddf4ff] border-[#54aeff]'}`}
    >
      <div
        className={`text-xs font-semibold mb-1 ${destructive ? 'text-[#cf222e]' : 'text-[#0969da]'}`}
      >
        {destructive
          ? '⚠ Destructive action — needs your approval'
          : 'Needs your approval'}
      </div>
      <div className="text-sm text-[#1f2328] mb-2">{summary}</div>
      {isSaveTool && (
        <div className="flex items-center gap-2 mb-2">
          <input
            value={stem}
            onChange={(e) => setStem(e.target.value)}
            placeholder={
              entry.name === 'save_workflow' ? 'filename-stem' : 'plugin_name'
            }
            className="flex-1 rounded border border-[#d0d7de] bg-white px-2 py-1 text-xs text-[#1f2328] focus:outline-none focus:border-[#0969da]"
          />
          <span className="text-[#adbac7] text-xs">
            {entry.name === 'save_workflow' ? '.yaml' : '.py'}
          </span>
        </div>
      )}
      {error && <div className="mb-2 text-xs text-[#d1242f]">{error}</div>}
      <div className="flex gap-2">
        <button
          onClick={approve}
          disabled={busy || (isSaveTool && !stem.trim())}
          className={`px-3 py-1.5 rounded text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors ${destructive ? 'bg-[#cf222e] hover:bg-[#a40e26]' : 'bg-[#0969da] hover:bg-[#0860ca]'}`}
        >
          {busy ? 'Working…' : approveLabel}
        </button>
        <button
          onClick={() => onResolve([{ id: entry.id, outcome: 'cancelled' }])}
          disabled={busy}
          className="px-3 py-1.5 rounded border border-[#d0d7de] text-[#656d76] text-sm hover:bg-[#eaeef2] disabled:opacity-40 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Bulk approval — appears above the stacked cards when 2+ proposals from the
// same turn can be applied together (e.g. several records proposed at once).
// Destructive and save_* proposals are excluded and always need an individual
// click, so a single click can never approve something the user hasn't seen.
// ---------------------------------------------------------------------------

function BulkApprovalBar({
  entries,
  onResolve,
}: {
  entries: ToolCallEntry[]
  onResolve: (resolutions: ResolvedEntry[]) => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const bulkable = entries.filter(isBulkable)

  if (bulkable.length < 2) return null

  async function approveAll() {
    setBusy(true)
    setError('')
    // Collect every resolution locally and resolve them in one combined call
    // at the end (rather than once per item) -- so the chat only auto-continues
    // once for the whole batch, not once per approved item.
    const resolutions: ResolvedEntry[] = []
    for (const entry of bulkable) {
      try {
        const result = await applyProposal(entry)
        resolutions.push({ id: entry.id, ...result })
      } catch (e) {
        const label = parseResult(entry.result)?.summary ?? entry.name
        setError(
          `Stopped at "${label}": ${e instanceof Error ? e.message : String(e)}`,
        )
        break
      }
    }
    if (resolutions.length > 0) onResolve(resolutions)
    setBusy(false)
  }

  return (
    <div className="flex items-center justify-between gap-2 rounded-md border border-[#d0d7de] bg-white px-3 py-2 text-xs">
      <span className="text-[#656d76]">
        {bulkable.length} changes from this turn can be approved together
      </span>
      <div className="flex items-center gap-2">
        {error && <span className="text-[#d1242f]">{error}</span>}
        <button
          onClick={approveAll}
          disabled={busy}
          className="flex-shrink-0 px-2.5 py-1 rounded bg-[#0969da] text-white font-medium hover:bg-[#0860ca] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {busy ? 'Approving…' : `Approve all ${bulkable.length}`}
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

interface AiPanelProps {
  open: boolean
  onClose: () => void
}

export default function AiPanel({ open, onClose }: AiPanelProps) {
  const [entries, setEntries] = useState<ChatEntry[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [fullscreen, setFullscreen] = useState(false)
  const [sessionId, setSessionId] = useState(() => `${Date.now()}`)
  const [sessions, setSessions] = useState<StoredSession[]>([])
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Restore most recent session on mount
  useEffect(() => {
    const stored = loadSessions()
    setSessions(stored)
    if (stored.length > 0 && stored[0]) {
      const s = stored[0]
      setEntries(
        s.entries.map((e) =>
          e.kind === 'assistant' ? { ...e, streaming: false } : e,
        ),
      )
      setSessionId(s.id)
    }
  }, [])

  // Auto-save whenever a complete assistant response arrives
  useEffect(() => {
    if (entries.length === 0) return
    const hasComplete = entries.some(
      (e) => e.kind === 'assistant' && !e.streaming,
    )
    if (!hasComplete) return
    const firstUser =
      (entries.find((e) => e.kind === 'user') as UserEntry | undefined)?.text ??
      ''
    const title = firstUser.slice(0, 70) || 'Chat'
    setSessions((prev) => {
      const without = prev.filter((s) => s.id !== sessionId)
      const updated = [
        { id: sessionId, title, createdAt: new Date().toISOString(), entries },
        ...without,
      ].slice(0, MAX_SESSIONS)
      saveSessions(updated)
      return updated
    })
  }, [entries, sessionId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [entries])

  function startNewChat() {
    setEntries([])
    setInput('')
    setSessionId(`${Date.now()}`)
    setShowHistory(false)
  }

  function restoreSession(session: StoredSession) {
    setEntries(
      session.entries.map((e) =>
        e.kind === 'assistant' ? { ...e, streaming: false } : e,
      ),
    )
    setSessionId(session.id)
    setShowHistory(false)
  }

  function deleteSession(id: string, e: React.MouseEvent) {
    e.stopPropagation()
    setSessions((prev) => {
      const updated = prev.filter((s) => s.id !== id)
      saveSessions(updated)
      return updated
    })
  }

  function toApiMessages(ents: ChatEntry[]): ChatMessage[] {
    const msgs: ChatMessage[] = []
    for (const e of ents) {
      if (e.kind === 'user' || e.kind === 'assistant') {
        msgs.push({ role: e.kind, content: e.text })
      } else if (e.kind === 'tool_call' && e.result !== null) {
        // Preserve the tool call + its result so the model still has it in
        // view on later turns. A null result means the stream was
        // interrupted before this tool call resolved -- there's nothing
        // valid to pair it with, so it's dropped rather than resent broken.
        msgs.push({
          role: 'tool_call',
          id: e.id,
          name: e.name,
          input: e.input,
          result: resultForApi(e),
        })
      }
    }
    return msgs
  }

  // Streams one assistant turn from `msgs` and applies the resulting events.
  // Shared by handleSend (a new user message) and resolveAndContinue (an
  // automatic continuation after a proposal is resolved) so both go through
  // the exact same request/response handling.
  async function runStream(msgs: ChatMessage[]) {
    setBusy(true)
    setEntries((prev) => [
      ...prev,
      { kind: 'assistant', text: '', streaming: true },
    ])
    try {
      for await (const event of streamChat(msgs)) {
        setEntries((prev) => applyEvent(prev, event))
        if (event.type === 'done' || event.type === 'error') break
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setEntries((prev) => [
        ...prev.slice(0, -1),
        { kind: 'assistant', text: `Error: ${msg}`, streaming: false },
      ])
    } finally {
      setBusy(false)
    }
  }

  // Records the outcome(s) of one or more resolved proposals, then
  // automatically continues the conversation — the model gets a chance to
  // react (e.g. move on to the next step of a multi-part request) without
  // the user having to manually prompt it after every approval. This is a
  // deterministic continuation of the existing tool-round-trip mechanism
  // (see civex.server.routers.ai's proposal-halt comment), not something the
  // model is instructed to do on its own.
  async function resolveAndContinue(resolutions: ResolvedEntry[]) {
    if (busy) return
    const updated = entries.map((e) => {
      if (e.kind !== 'tool_call') return e
      const r = resolutions.find((x) => x.id === e.id)
      return r ? { ...e, outcome: r.outcome, outcomeLabel: r.outcomeLabel } : e
    })
    setEntries(updated)
    await runStream(toApiMessages(updated))
  }

  async function handleSend() {
    const text = input.trim()
    if (!text || busy) return
    setInput('')

    const userEntry: UserEntry = { kind: 'user', text }
    const nextEntries = [...entries, userEntry]
    setEntries((prev) => [...prev, userEntry])
    await runStream(toApiMessages(nextEntries))
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const containerClass = fullscreen
    ? `fixed inset-0 flex flex-col bg-white z-50 ${open ? '' : 'hidden'}`
    : `fixed inset-y-0 right-0 w-[420px] flex flex-col bg-white border-l border-[#d0d7de] shadow-2xl z-50 ${open ? '' : 'hidden'}`

  const bodyClass = fullscreen
    ? 'flex-1 flex flex-col overflow-hidden max-w-3xl mx-auto w-full'
    : 'flex-1 flex flex-col overflow-hidden'

  // Every unresolved proposal from the thread, in chronological order. A
  // single turn can propose several changes at once (e.g. parallel tool
  // calls), so this is a list, not a single entry — each gets its own card
  // (keyed by id) rather than forcing one-at-a-time reverse-order approval.
  const pendingEntries: ToolCallEntry[] = busy
    ? []
    : entries.filter(
        (e): e is ToolCallEntry =>
          e.kind === 'tool_call' && isPendingApproval(e),
      )

  return (
    <div className={containerClass}>
      {/* Header */}
      <div className="flex items-center border-b border-[#d0d7de] bg-[#f6f8fa] px-4 py-3">
        <div
          className={`flex items-center gap-2 w-full ${fullscreen ? 'max-w-3xl mx-auto' : ''}`}
        >
          <span className="text-[#0969da]">✦</span>
          <span className="text-sm font-semibold text-[#1f2328]">civex AI</span>
          <div className="flex-1" />
          {/* History button */}
          <button
            onClick={() => {
              setShowHistory((h) => !h)
              setShowSettings(false)
            }}
            title={showHistory ? 'Back to chat' : 'Chat history'}
            className={`p-1 transition-colors ${showHistory ? 'text-[#0969da]' : 'text-[#656d76] hover:text-[#1f2328]'}`}
          >
            <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor">
              <path d="M1.643 3.143L.427 1.927A.25.25 0 0 0 0 2.104V5.75c0 .138.112.25.25.25h3.646a.25.25 0 0 0 .177-.427L2.715 4.215a6.5 6.5 0 1 1-1.18 4.458.75.75 0 1 0-1.493.154 8 8 0 1 0 1.6-5.684ZM8 5.25a.75.75 0 0 1 .75.75v2.69l1.28 1.28a.75.75 0 0 1-1.06 1.06L7.22 9.28A.75.75 0 0 1 7 8.75V6A.75.75 0 0 1 8 5.25Z" />
            </svg>
          </button>
          {/* Settings button */}
          <button
            onClick={() => {
              setShowSettings((s) => !s)
              setShowHistory(false)
            }}
            title={showSettings ? 'Back to chat' : 'AI settings'}
            className={`p-1 transition-colors ${showSettings ? 'text-[#0969da]' : 'text-[#656d76] hover:text-[#1f2328]'}`}
          >
            <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor">
              <path d="M8 0a8.2 8.2 0 0 1 .701.031C9.444.095 9.99.645 9.99 1.311v.171a6.946 6.946 0 0 1 1.524.625l.121-.12a1.311 1.311 0 0 1 1.855 0l.354.353a1.311 1.311 0 0 1 0 1.855l-.12.121c.247.473.43.98.524 1.524h.171c.666 0 1.216.546 1.28 1.29A8.2 8.2 0 0 1 16 8a8.2 8.2 0 0 1-.031.701c-.064.744-.614 1.29-1.28 1.29h-.171a6.946 6.946 0 0 1-.524 1.524l.12.121a1.311 1.311 0 0 1 0 1.855l-.353.354a1.311 1.311 0 0 1-1.855 0l-.121-.12a6.946 6.946 0 0 1-1.524.524v.171c0 .666-.546 1.216-1.29 1.28A8.2 8.2 0 0 1 8 16a8.2 8.2 0 0 1-.701-.031c-.744-.064-1.29-.614-1.29-1.28v-.171a6.946 6.946 0 0 1-1.524-.524l-.121.12a1.311 1.311 0 0 1-1.855 0l-.354-.353a1.311 1.311 0 0 1 0-1.855l.12-.121A6.946 6.946 0 0 1 2.25 10.7h-.171c-.666 0-1.216-.546-1.28-1.29A8.2 8.2 0 0 1 0 8a8.2 8.2 0 0 1 .031-.701C.095 6.556.645 6.01 1.311 6.01h.171a6.946 6.946 0 0 1 .524-1.524l-.12-.121a1.311 1.311 0 0 1 0-1.855l.353-.354a1.311 1.311 0 0 1 1.855 0l.121.12A6.946 6.946 0 0 1 5.74 1.77h-.17v-.17c0-.666.545-1.216 1.29-1.28A8.233 8.233 0 0 1 8 .001Zm-.5 4.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z" />
            </svg>
          </button>
          {/* Fullscreen toggle */}
          <button
            onClick={() => setFullscreen((f) => !f)}
            title={fullscreen ? 'Exit full screen' : 'Full screen'}
            className="p-1 text-[#656d76] hover:text-[#1f2328] transition-colors"
          >
            {fullscreen ? (
              <svg
                width="15"
                height="15"
                viewBox="0 0 16 16"
                fill="currentColor"
              >
                <path d="M5.5 0a.5.5 0 0 1 .5.5v4a.5.5 0 0 1-.5.5h-4a.5.5 0 0 1 0-1H5V.5a.5.5 0 0 1 .5-.5Zm5 0a.5.5 0 0 1 .5.5V5h3.5a.5.5 0 0 1 0 1h-4a.5.5 0 0 1-.5-.5v-4a.5.5 0 0 1 .5-.5ZM0 10.5a.5.5 0 0 1 .5-.5h4a.5.5 0 0 1 .5.5v4a.5.5 0 0 1-1 0V11H.5a.5.5 0 0 1-.5-.5Zm11 0a.5.5 0 0 1 .5-.5h4a.5.5 0 0 1 0 1H12v3.5a.5.5 0 0 1-1 0v-4Z" />
              </svg>
            ) : (
              <svg
                width="15"
                height="15"
                viewBox="0 0 16 16"
                fill="currentColor"
              >
                <path d="M1.5 1h4a.5.5 0 0 1 0 1H2v3.5a.5.5 0 0 1-1 0v-4a.5.5 0 0 1 .5-.5Zm9 0h4a.5.5 0 0 1 .5.5v4a.5.5 0 0 1-1 0V2h-3.5a.5.5 0 0 1 0-1ZM1 10.5a.5.5 0 0 1 .5-.5.5.5 0 0 1 .5.5V14h3.5a.5.5 0 0 1 0 1h-4a.5.5 0 0 1-.5-.5v-4Zm13 0v4a.5.5 0 0 1-.5.5h-4a.5.5 0 0 1 0-1H14v-3.5a.5.5 0 0 1 .5-.5.5.5 0 0 1 .5.5Z" />
              </svg>
            )}
          </button>
          <button
            onClick={onClose}
            className="text-[#656d76] hover:text-[#1f2328] transition-colors p-1"
            aria-label="Close"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
              <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
            </svg>
          </button>
        </div>
      </div>

      {/* Body — centered in fullscreen */}
      <div className={bodyClass}>
        {/* Settings pane */}
        {showSettings && (
          <div className="flex-1 overflow-y-auto">
            <SettingsPane onSaved={() => setShowSettings(false)} />
          </div>
        )}

        {/* History pane */}
        {showHistory && (
          <HistoryPane
            sessions={sessions}
            onRestore={restoreSession}
            onDelete={deleteSession}
            onNewChat={startNewChat}
          />
        )}

        {/* Messages */}
        <div
          className={`flex-1 overflow-y-auto px-4 py-4 space-y-3 ${showSettings || showHistory ? 'hidden' : ''}`}
        >
          {entries.length === 0 && (
            <div className="text-center py-12 text-[#656d76] text-sm space-y-3">
              <div className="text-3xl">✦</div>
              <p className="font-medium text-[#1f2328]">Ask me anything</p>
              <div className="text-xs space-y-1.5 text-left max-w-[280px] mx-auto">
                <p className="text-[#656d76]">Try:</p>
                {[
                  'How many records do I have?',
                  'What field types does civex support?',
                  'Create a workflow that extracts dates from filenames',
                  'Write a plugin that calls an external API',
                ].map((s) => (
                  <button
                    key={s}
                    onClick={() => {
                      setInput(s)
                      textareaRef.current?.focus()
                    }}
                    className="block w-full text-left px-3 py-1.5 rounded border border-[#d0d7de] bg-white hover:bg-[#f6f8fa] text-[#1f2328] transition-colors"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {entries.map((entry, i) => {
            if (entry.kind === 'user') {
              return (
                <div key={i} className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-tr-sm px-4 py-2 bg-[#24292f] text-white text-sm whitespace-pre-wrap">
                    {entry.text}
                  </div>
                </div>
              )
            }
            if (entry.kind === 'assistant') {
              return (
                <div key={i} className="flex justify-start">
                  <div className="max-w-[95%]">
                    <AssistantText
                      text={entry.text}
                      streaming={entry.streaming}
                    />
                  </div>
                </div>
              )
            }
            return <ToolCallRow key={i} entry={entry} />
          })}

          <div ref={bottomRef} />
        </div>

        {/* Input (or the approval card(s) when proposed changes await the user) */}
        <div
          className={`border-t border-[#d0d7de] p-3 bg-[#f6f8fa] ${showSettings || showHistory ? 'hidden' : ''}`}
        >
          {pendingEntries.length > 0 ? (
            <div className="space-y-2">
              <BulkApprovalBar
                entries={pendingEntries}
                onResolve={resolveAndContinue}
              />
              <div
                className={`space-y-2 ${pendingEntries.length > 2 ? 'max-h-64 overflow-y-auto pr-0.5' : ''}`}
              >
                {pendingEntries.map((e) => (
                  <ApprovalBar
                    key={e.id}
                    entry={e}
                    onResolve={resolveAndContinue}
                  />
                ))}
              </div>
            </div>
          ) : (
            <>
              <div className="flex gap-2 items-end">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask about your data or describe a workflow…"
                  rows={2}
                  disabled={busy}
                  className="flex-1 resize-none rounded-md border border-[#d0d7de] bg-white px-3 py-2 text-sm text-[#1f2328] placeholder:text-[#adbac7] focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da] disabled:opacity-50"
                />
                <button
                  onClick={handleSend}
                  disabled={busy || !input.trim()}
                  className="flex-shrink-0 px-3 py-2 rounded-md bg-[#0969da] text-white text-sm font-medium hover:bg-[#0860ca] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {busy ? (
                    <svg
                      className="animate-spin w-4 h-4"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2.5"
                    >
                      <path
                        d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"
                        strokeLinecap="round"
                      />
                    </svg>
                  ) : (
                    <svg
                      width="16"
                      height="16"
                      viewBox="0 0 16 16"
                      fill="currentColor"
                    >
                      <path d="M1.5 2.75a.75.75 0 0 1 .75-.75h.75a.75.75 0 0 1 0 1.5H3V7h10V3.5H12a.75.75 0 0 1 0-1.5h.75a.75.75 0 0 1 .75.75v5a.75.75 0 0 1-.75.75H9.56l1.22 1.22a.75.75 0 0 1-1.06 1.06l-2.5-2.5a.75.75 0 0 1 0-1.06l2.5-2.5a.75.75 0 1 1 1.06 1.06L9.56 7.5h2.69V8H3V7.5h2.69L4.47 6.28a.75.75 0 0 1 1.06-1.06l2.5 2.5a.75.75 0 0 1 0 1.06l-2.5 2.5a.75.75 0 0 1-1.06-1.06L5.69 8.5H3V8H3V3.5H2.25a.75.75 0 0 1-.75-.75Z" />
                    </svg>
                  )}
                </button>
              </div>
              <p className="mt-1.5 text-[10px] text-[#adbac7] text-center">
                Enter to send · Shift+Enter for new line
              </p>
            </>
          )}
        </div>
      </div>
      {/* /body */}
    </div>
  )
}

// ---------------------------------------------------------------------------
// History pane
// ---------------------------------------------------------------------------

function HistoryPane({
  sessions,
  onRestore,
  onDelete,
  onNewChat,
}: {
  sessions: StoredSession[]
  onRestore: (s: StoredSession) => void
  onDelete: (id: string, e: React.MouseEvent) => void
  onNewChat: () => void
}) {
  return (
    <div className="flex-1 overflow-y-auto flex flex-col min-h-0">
      <div className="p-3 border-b border-[#d0d7de] flex-shrink-0">
        <button
          onClick={onNewChat}
          className="w-full py-1.5 rounded-md bg-[#0969da] text-white text-sm font-medium hover:bg-[#0860ca] transition-colors"
        >
          + New chat
        </button>
      </div>
      {sessions.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-xs text-[#adbac7]">
          No saved sessions yet
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto divide-y divide-[#eaeef2]">
          {sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => onRestore(s)}
              className="w-full text-left px-4 py-3 hover:bg-[#f6f8fa] transition-colors group"
            >
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm text-[#1f2328] truncate flex-1">
                  {s.title}
                </p>
                <span
                  role="button"
                  onClick={(e) =>
                    onDelete(s.id, e as unknown as React.MouseEvent)
                  }
                  className="text-[#d0d7de] hover:text-[#d1242f] transition-colors opacity-0 group-hover:opacity-100 flex-shrink-0 cursor-pointer"
                  title="Delete session"
                >
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 16 16"
                    fill="currentColor"
                  >
                    <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
                  </svg>
                </span>
              </div>
              <p className="text-[10px] text-[#adbac7] mt-0.5">
                {relativeTime(s.createdAt)}
              </p>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Settings pane
// ---------------------------------------------------------------------------

function detectPreset(cfg: AiConfig | null): PresetProviderId {
  if (!cfg?.configured) return 'groq'
  if (cfg.provider === 'anthropic') return 'anthropic'
  const groq = PRESET_PROVIDERS.find((p) => p.id === 'groq')!
  const gemini = PRESET_PROVIDERS.find((p) => p.id === 'gemini')!
  const ollama = PRESET_PROVIDERS.find((p) => p.id === 'ollama')!
  const openrouter = PRESET_PROVIDERS.find((p) => p.id === 'openrouter')!
  if (cfg.base_url === groq.base_url) return 'groq'
  if (cfg.base_url === gemini.base_url) return 'gemini'
  if (cfg.base_url === openrouter.base_url) return 'openrouter'
  if (
    cfg.base_url?.startsWith('http://localhost:11434') ||
    cfg.base_url === ollama.base_url
  )
    return 'ollama'
  return 'custom'
}

function SettingsPane({ onSaved }: { onSaved: () => void }) {
  const [cfg, setCfg] = useState<AiConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [preset, setPreset] = useState<PresetProviderId>('groq')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [customBaseUrl, setCustomBaseUrl] = useState('')
  const [customModel, setCustomModel] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)
  const [orLimits, setOrLimits] = useState<OpenRouterLimits | null>(null)
  const [orPolling, setOrPolling] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [ollamaModels, setOllamaModels] = useState<OllamaModel[]>([])
  const [ollamaLoading, setOllamaLoading] = useState(false)
  const [ollamaError, setOllamaError] = useState<string | null>(null)

  useEffect(() => {
    getAiConfig()
      .then((c) => {
        setCfg(c)
        const p = detectPreset(c)
        setPreset(p)
        setModel(c.model)
        if (p === 'custom' || p === 'ollama') {
          setCustomBaseUrl(c.base_url ?? '')
          setCustomModel(c.model)
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const presetObj = PRESET_PROVIDERS.find((p) => p.id === preset)!

  function handlePresetChange(newPreset: PresetProviderId) {
    setPreset(newPreset)
    setError(null)
    const p = PRESET_PROVIDERS.find((x) => x.id === newPreset)!
    if (p.models.length > 0) {
      setModel(p.models[0]?.id ?? '')
    } else if (newPreset === 'ollama') {
      const ollamaPreset = p as typeof p & { defaultModel?: string }
      setCustomModel(ollamaPreset.defaultModel ?? 'qwen2.5:7b')
      setCustomBaseUrl(p.base_url as string)
    } else {
      setModel(customModel)
    }
  }

  // Fetch Ollama models whenever the ollama preset is selected or base URL changes
  useEffect(() => {
    if (preset !== 'ollama') {
      setOllamaModels([])
      setOllamaError(null)
      return
    }
    setOllamaLoading(true)
    setOllamaError(null)
    const url = customBaseUrl || 'http://localhost:11434/v1'
    getOllamaModels(url)
      .then((models) => {
        setOllamaModels(models)
        if (models.length > 0) {
          setCustomModel((prev) => prev || models[0].name)
        }
      })
      .catch((e) => setOllamaError(e instanceof Error ? e.message : String(e)))
      .finally(() => setOllamaLoading(false))
  }, [preset, customBaseUrl])

  // Fetch OpenRouter limits whenever we're on the openrouter preset and configured
  useEffect(() => {
    if (!cfg?.configured || detectPreset(cfg) !== 'openrouter') return
    getOpenRouterLimits()
      .then(setOrLimits)
      .catch(() => {})
    const id = setInterval(
      () =>
        getOpenRouterLimits()
          .then(setOrLimits)
          .catch(() => {}),
      30_000,
    )
    return () => clearInterval(id)
  }, [cfg])

  // Clean up polling interval on unmount
  useEffect(
    () => () => {
      if (pollRef.current) clearInterval(pollRef.current)
    },
    [],
  )

  async function handleOpenRouterLogin() {
    try {
      const url = await getOpenRouterAuthUrl()
      window.open(url, '_blank', 'width=600,height=700')
      setOrPolling(true)
      pollRef.current = setInterval(async () => {
        try {
          const updated = await getAiConfig()
          if (
            updated.configured &&
            updated.base_url?.includes('openrouter.ai')
          ) {
            setCfg(updated)
            setPreset('openrouter')
            setModel(updated.model)
            setOrPolling(false)
            if (pollRef.current) clearInterval(pollRef.current)
            setSuccess(true)
            setTimeout(() => setSuccess(false), 2000)
          }
        } catch {
          /* ignore */
        }
      }, 1500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function handleSave() {
    setError(null)
    setSuccess(false)
    setSaving(true)
    try {
      const isCustom = preset === 'custom'
      const isOllama = preset === 'ollama'
      const isOpenRouter = preset === 'openrouter'
      const isAnthropic = preset === 'anthropic'
      const provider = isAnthropic ? 'anthropic' : 'openai-compat'
      const base_url = isAnthropic
        ? null
        : isCustom || isOllama
          ? customBaseUrl.trim()
          : (presetObj.base_url as string)
      const resolvedModel = isCustom || isOllama ? customModel.trim() : model

      const patch: Record<string, unknown> = {
        provider,
        base_url,
        model: resolvedModel,
      }
      if (apiKey.trim()) {
        patch.api_key = apiKey.trim()
      } else if (isOllama) {
        patch.api_key = 'ollama'
      } else if (isOpenRouter && cfg?.configured) {
        // keep existing key from OAuth
      } else if (isOpenRouter && !cfg?.configured) {
        setError(
          'Use the "Login with OpenRouter" button to connect, or paste a key manually.',
        )
        setSaving(false)
        return
      } else if (!cfg?.configured) {
        setError('API key is required')
        setSaving(false)
        return
      }

      const updated = await updateAiConfig(patch)
      setCfg(updated)
      setApiKey('')
      setSuccess(true)
      setTimeout(() => {
        setSuccess(false)
        onSaved()
      }, 1200)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="p-4 text-sm text-[#656d76]">Loading…</div>

  const isCustom = preset === 'custom'
  const isOllama = preset === 'ollama'
  const isOpenRouter = preset === 'openrouter'
  const isFreeText = isCustom || isOllama
  const isAnthropic = preset === 'anthropic'
  const effectiveModel = isFreeText ? customModel : model

  return (
    <div className="p-4 space-y-4 text-sm">
      <div>
        <p className="font-semibold text-[#1f2328] mb-1">
          AI Assistant Settings
        </p>
        {cfg?.configured ? (
          <p className="text-xs text-[#3fb950]">
            ✓{' '}
            {cfg.provider === 'anthropic'
              ? 'Claude'
              : cfg.base_url?.includes('groq')
                ? 'Groq'
                : cfg.base_url?.includes('google')
                  ? 'Gemini'
                  : cfg.base_url?.includes('openrouter')
                    ? 'OpenRouter'
                    : cfg.base_url?.includes('11434')
                      ? 'Ollama'
                      : 'Custom'}{' '}
            —{' '}
            {cfg.base_url?.includes('11434') ||
            cfg.base_url?.includes('openrouter')
              ? cfg.model
              : `key ${cfg.key_hint}`}
            {cfg.source === 'env' && (
              <span className="text-[#adbac7] ml-1">(via env)</span>
            )}
          </p>
        ) : (
          <p className="text-xs text-[#f85149]">Not configured</p>
        )}
      </div>

      {/* Provider */}
      <div>
        <label className="block text-xs font-medium text-[#1f2328] mb-1">
          Provider
        </label>
        <select
          value={preset}
          onChange={(e) =>
            handlePresetChange(e.target.value as PresetProviderId)
          }
          className="w-full rounded-md border border-[#d0d7de] px-3 py-1.5 text-sm text-[#1f2328] bg-white focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]"
        >
          {PRESET_PROVIDERS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
        {presetObj.docs && !isOllama && (
          <p className="mt-1 text-[10px] text-[#adbac7]">
            Get a free API key at{' '}
            <a
              href={presetObj.docs}
              target="_blank"
              rel="noreferrer"
              className="text-[#0969da] hover:underline"
            >
              {presetObj.docs.replace('https://', '')}
            </a>
          </p>
        )}
        {isOllama && (
          <p className="mt-1 text-[10px] text-[#adbac7]">
            {'note' in presetObj ? (presetObj as { note: string }).note : ''}{' '}
            <a
              href="https://ollama.com"
              target="_blank"
              rel="noreferrer"
              className="text-[#0969da] hover:underline"
            >
              ollama.com
            </a>
          </p>
        )}
        {isOpenRouter && (
          <p className="mt-1 text-[10px] text-[#adbac7]">
            {'note' in presetObj ? (presetObj as { note: string }).note : ''}
          </p>
        )}
      </div>

      {/* Base URL — editable for ollama and custom */}
      {(isCustom || isOllama) && (
        <div>
          <label className="block text-xs font-medium text-[#1f2328] mb-1">
            Base URL
          </label>
          <input
            value={customBaseUrl}
            onChange={(e) => setCustomBaseUrl(e.target.value)}
            placeholder="http://localhost:11434/v1"
            className="w-full rounded-md border border-[#d0d7de] px-3 py-1.5 text-sm text-[#1f2328] placeholder:text-[#adbac7] focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]"
          />
          {isOllama && (
            <p className="mt-1 text-[10px] text-[#adbac7]">
              Change if Ollama runs on a different host/port.
            </p>
          )}
        </div>
      )}

      {/* OpenRouter OAuth + limits */}
      {isOpenRouter && (
        <div className="space-y-2">
          <button
            onClick={handleOpenRouterLogin}
            disabled={orPolling}
            className="w-full py-1.5 rounded-md border border-[#d0d7de] bg-white text-sm font-medium text-[#1f2328] hover:bg-[#f6f8fa] disabled:opacity-50 transition-colors flex items-center justify-center gap-2"
          >
            {orPolling ? (
              <>
                <svg
                  className="animate-spin w-3.5 h-3.5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                >
                  <path
                    d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"
                    strokeLinecap="round"
                  />
                </svg>
                Waiting for login…
              </>
            ) : (
              <>
                {cfg?.configured && detectPreset(cfg) === 'openrouter'
                  ? '↺ Reconnect with OpenRouter'
                  : '→ Login with OpenRouter'}
              </>
            )}
          </button>

          {/* Live limits widget */}
          {orLimits && (
            <div className="rounded-md border border-[#d0d7de] bg-[#f6f8fa] px-3 py-2 text-xs space-y-1">
              <div className="flex justify-between text-[#1f2328]">
                <span className="font-medium">Daily request limit</span>
                <span>
                  {orLimits.data.rate_limit?.requests ?? '—'} /{' '}
                  {orLimits.data.rate_limit?.interval ?? 'day'}
                </span>
              </div>
              {orLimits.data.limit !== null && (
                <div className="flex justify-between text-[#656d76]">
                  <span>Credit usage</span>
                  <span>${orLimits.data.usage.toFixed(4)}</span>
                </div>
              )}
              <div className="flex justify-between text-[#656d76]">
                <span>Free tier</span>
                <span>{orLimits.data.is_free_tier ? 'Yes' : 'No'}</span>
              </div>
              <p className="text-[10px] text-[#adbac7] pt-0.5">
                Refreshes every 30 s. Limit resets daily.
              </p>
            </div>
          )}

          <p className="text-[10px] text-[#adbac7]">
            Or paste a key manually below.
          </p>
        </div>
      )}

      {/* API key */}
      {!isOllama && (
        <div>
          <label className="block text-xs font-medium text-[#1f2328] mb-1">
            API key
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={
              cfg?.configured
                ? `Current: ${cfg.key_hint}`
                : presetObj.key_placeholder
            }
            className="w-full rounded-md border border-[#d0d7de] px-3 py-1.5 text-sm text-[#1f2328] placeholder:text-[#adbac7] focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]"
          />
          <p className="mt-1 text-[10px] text-[#adbac7]">
            {cfg?.configured
              ? 'Leave blank to keep existing key.'
              : 'Required.'}{' '}
            Saved to _civex/config.toml.
          </p>
        </div>
      )}

      {/* Model */}
      <div>
        <label className="block text-xs font-medium text-[#1f2328] mb-1">
          Model
        </label>
        {isOllama ? (
          ollamaLoading ? (
            <div className="flex items-center gap-2 text-xs text-[#656d76] py-1.5">
              <svg
                className="animate-spin w-3.5 h-3.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
              >
                <path
                  d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"
                  strokeLinecap="round"
                />
              </svg>
              Detecting installed models…
            </div>
          ) : ollamaError ? (
            <div className="space-y-1.5">
              <p className="text-xs text-[#d1242f]">{ollamaError}</p>
              <p className="text-[10px] text-[#adbac7]">
                Make sure Ollama is running:{' '}
                <code className="bg-[#eaeef2] px-1 rounded">ollama serve</code>
              </p>
              <input
                value={customModel}
                onChange={(e) => setCustomModel(e.target.value)}
                placeholder="qwen2.5:7b"
                className="w-full rounded-md border border-[#d0d7de] px-3 py-1.5 text-sm text-[#1f2328] placeholder:text-[#adbac7] focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]"
              />
            </div>
          ) : ollamaModels.length === 0 ? (
            <div className="space-y-1.5">
              <p className="text-xs text-[#656d76]">No models installed.</p>
              <p className="text-[10px] text-[#adbac7]">
                Run{' '}
                <code className="bg-[#eaeef2] px-1 rounded">
                  ollama pull qwen2.5:7b
                </code>{' '}
                then refresh.
              </p>
            </div>
          ) : (
            <div className="space-y-1">
              <select
                value={customModel}
                onChange={(e) => setCustomModel(e.target.value)}
                className="w-full rounded-md border border-[#d0d7de] px-3 py-1.5 text-sm text-[#1f2328] bg-white focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]"
              >
                {ollamaModels.map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name} —{' '}
                    {m.size >= 1e9
                      ? `${(m.size / 1e9).toFixed(1)} GB`
                      : `${Math.round(m.size / 1e6)} MB`}
                  </option>
                ))}
              </select>
              <p className="text-[10px] text-[#adbac7]">
                {ollamaModels.length} model
                {ollamaModels.length !== 1 ? 's' : ''} installed. Tool calling
                requires qwen2.5, llama3.1, or mistral.
              </p>
            </div>
          )
        ) : isFreeText || presetObj.models.length === 0 ? (
          <input
            value={customModel}
            onChange={(e) => setCustomModel(e.target.value)}
            placeholder={isAnthropic ? 'claude-sonnet-4-6' : 'model name'}
            className="w-full rounded-md border border-[#d0d7de] px-3 py-1.5 text-sm text-[#1f2328] placeholder:text-[#adbac7] focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]"
          />
        ) : (
          <select
            value={effectiveModel || presetObj.models[0]?.id || ''}
            onChange={(e) => setModel(e.target.value)}
            className="w-full rounded-md border border-[#d0d7de] px-3 py-1.5 text-sm text-[#1f2328] bg-white focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]"
          >
            {presetObj.models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        )}
      </div>

      {error && <p className="text-xs text-[#d1242f]">{error}</p>}
      {success && <p className="text-xs text-[#3fb950]">✓ Saved</p>}

      <button
        onClick={handleSave}
        disabled={saving}
        className="w-full py-1.5 rounded-md bg-[#0969da] text-white text-sm font-medium hover:bg-[#0860ca] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        {saving ? 'Saving…' : 'Save'}
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// State reducer helper
// ---------------------------------------------------------------------------

function applyEvent(prev: ChatEntry[], event: AiEvent): ChatEntry[] {
  switch (event.type) {
    case 'text_delta': {
      const last = prev[prev.length - 1]
      if (last?.kind === 'assistant') {
        return [
          ...prev.slice(0, -1),
          { ...last, text: last.text + event.delta },
        ]
      }
      return [
        ...prev,
        { kind: 'assistant', text: event.delta, streaming: true },
      ]
    }
    case 'tool_use_start':
      return [
        ...prev,
        {
          kind: 'tool_call',
          id: event.id,
          name: event.name,
          input: event.input,
          result: null,
        },
      ]
    case 'tool_result':
      return prev.map((e) =>
        e.kind === 'tool_call' && e.id === event.tool_use_id
          ? { ...e, result: event.content }
          : e,
      )
    case 'done':
      // Clear streaming on every assistant entry — after a proposal halt the last
      // entry is the tool call, so targeting only the last entry would leave the
      // assistant message stuck "streaming".
      return prev.map((e) =>
        e.kind === 'assistant' && e.streaming ? { ...e, streaming: false } : e,
      )
    case 'error': {
      const last = prev[prev.length - 1]
      if (last?.kind === 'assistant') {
        return [
          ...prev.slice(0, -1),
          { ...last, text: `⚠ ${event.message}`, streaming: false },
        ]
      }
      return [
        ...prev,
        { kind: 'assistant', text: `⚠ ${event.message}`, streaming: false },
      ]
    }
    default:
      return prev
  }
}
