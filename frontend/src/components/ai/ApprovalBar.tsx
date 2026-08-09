import { useState } from 'react'
import type { ResolvedEntry, ToolCallEntry } from '../../types/ai'
import { applyProposal, isSaveToolName, parseResult } from './proposals'
import { Field, Input } from '../ui'
import { AlertTriangle } from '../ui/icons'

// Pinned above the input while a proposal awaits the user.
//
// Rendered with `key={entry.id}` by the caller so each proposal gets a fresh
// component instance — otherwise React reuses the same instance across
// different proposals (same position in the tree) and stale `busy`/`stem`/
// `error` state bleeds from one approval into the next.
export default function ApprovalBar({
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
      className={`rounded-md border p-3 ${destructive ? 'bg-danger-subtle border-danger-muted' : 'bg-accent-subtle border-accent-muted'}`}
    >
      <div
        className={`flex items-center gap-1 text-xs font-semibold mb-1 ${destructive ? 'text-danger' : 'text-accent'}`}
      >
        {destructive ? (
          <>
            <AlertTriangle size={12} /> Destructive action — needs your approval
          </>
        ) : (
          'Needs your approval'
        )}
      </div>
      <div className="text-sm text-fg mb-2">{summary}</div>
      {isSaveTool && (
        <div className="flex items-center gap-2 mb-2">
          <Field label="Filename" hideLabel className="flex-1">
            <Input
              value={stem}
              onChange={(e) => setStem(e.target.value)}
              placeholder={
                entry.name === 'save_workflow' ? 'filename-stem' : 'plugin_name'
              }
              size="sm"
            />
          </Field>
          <span className="text-fg-subtle text-xs">
            {entry.name === 'save_workflow' ? '.yaml' : '.py'}
          </span>
        </div>
      )}
      {error && (
        <div role="alert" className="mb-2 text-xs text-danger">
          {error}
        </div>
      )}
      <div className="flex gap-2">
        <button
          onClick={approve}
          disabled={busy || (isSaveTool && !stem.trim())}
          className={`px-3 py-2 rounded-md text-fg-on-emphasis text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors ${destructive ? 'bg-danger hover:bg-danger-emphasis' : 'bg-accent hover:bg-accent-emphasis'}`}
        >
          {busy ? 'Working…' : approveLabel}
        </button>
        <button
          onClick={() => onResolve([{ id: entry.id, outcome: 'cancelled' }])}
          disabled={busy}
          className="px-3 py-2 rounded-md border border-border text-fg-muted text-sm hover:bg-border-muted disabled:opacity-40 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}
