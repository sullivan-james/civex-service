import { Paperclip, X } from '../ui/icons'
import { Button } from '../ui'
import { formatBytes } from '../../utils/restrictions'
import type { FileRef } from './DynamicField'

/** A file that has been uploaded to the object store but is not yet part of
 * the record. It only becomes the field's value when someone approves it. */
export interface StagedFile {
  ref: FileRef
  /** Why this file can't be approved, or null. */
  problem: string | null
}

/** The "waiting for approval" list under a file field. Nothing here touches
 * the record: approving hands the refs to the caller, discarding drops them
 * (the bytes stay in the content-addressed store until garbage collection). */
export function PendingFiles({
  staged,
  replacing,
  onDiscard,
  onApprove,
  onDiscardAll,
}: {
  staged: StagedFile[]
  /** Filename(s) the approval would replace, for a single-file field. */
  replacing?: string
  onDiscard: (sha256: string) => void
  onApprove: () => void
  onDiscardAll: () => void
}) {
  if (!staged.length) return null
  const blocked = staged.some((s) => s.problem)
  return (
    <div
      role="group"
      aria-label="Files waiting for approval"
      className="space-y-2 rounded-md border border-border bg-attention-subtle px-3 py-2"
    >
      <p className="text-xs font-semibold text-attention-emphasis">
        Waiting for approval — not saved to the record yet
      </p>
      {staged.map(({ ref, problem }) => (
        <div key={ref.sha256} className="space-y-0.5">
          <div className="flex items-center gap-2 text-sm text-fg">
            <Paperclip size={14} className="shrink-0 text-fg-muted" />
            <span className="truncate">{ref.filename}</span>
            <span className="shrink-0 text-xs text-fg-muted">
              {formatBytes(ref.size)}
            </span>
            <button
              type="button"
              onClick={() => onDiscard(ref.sha256)}
              aria-label={`Discard ${ref.filename}`}
              className="shrink-0 rounded p-1 text-fg-muted hover:bg-canvas-inset hover:text-danger cursor-pointer"
            >
              <X size={12} />
            </button>
          </div>
          {problem && (
            <p role="alert" className="pl-6 text-xs text-danger">
              {problem}
            </p>
          )}
        </div>
      ))}
      {replacing && (
        <p className="text-xs text-fg-muted">Replaces {replacing}.</p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="primary"
          onClick={onApprove}
          disabled={blocked}
        >
          {staged.length > 1 ? `Approve ${staged.length} files` : 'Approve'}
        </Button>
        <Button size="sm" onClick={onDiscardAll}>
          {staged.length > 1 ? 'Discard all' : 'Discard'}
        </Button>
      </div>
    </div>
  )
}
