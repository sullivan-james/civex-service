import { useState } from 'react'
import type { ResolvedEntry, ToolCallEntry } from '../../types/ai'
import { applyProposal, isBulkable, parseResult } from './proposals'

// Appears above the stacked cards when 2+ proposals from the same turn can
// be applied together (e.g. several records proposed at once). Destructive
// and save_* proposals are excluded and always need an individual click, so
// a single click can never approve something the user hasn't seen.
export default function BulkApprovalBar({
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
