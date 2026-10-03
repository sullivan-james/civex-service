import { useState } from 'react'
import { Badge, Button, ConfirmDialog } from '../../ui'
import { useDbMoves, useRevertMove } from '../../../hooks/useDb'
import type { MoveRecord } from '../../../api/db'
import { errorMessage } from '../../../lib/errors'

const BADGE = {
  done: 'success',
  failed: 'danger',
  cancelled: 'default',
  running: 'accent',
} as const

/** Past moves. The newest completed one that hasn't been undone can be
 * switched back from here -- the only one that can, since a project can only
 * go back to the database it last came from. */
export function MoveHistory() {
  const { data: moves } = useDbMoves()
  const revert = useRevertMove()
  const [confirming, setConfirming] = useState<MoveRecord | null>(null)

  if (!moves || moves.length === 0) return null
  const revertable = moves.find((m) => m.status === 'done' && !m.reverted_at)

  return (
    <>
      <ul className="divide-y divide-border-muted rounded-md border border-border bg-canvas">
        {moves.map((m) => (
          <li
            key={m.id}
            className="flex flex-wrap items-center justify-between gap-3 px-3 py-2 text-sm"
          >
            <div className="min-w-0">
              <p className="text-fg">
                {m.source_label} → {m.target_label}
              </p>
              <p className="text-xs text-fg-muted">
                {new Date(m.started_at).toLocaleString()}
                {m.error && ` · ${m.error}`}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant={BADGE[m.status]}>
                {m.reverted_at ? 'switched back' : m.status}
              </Badge>
              {m.id === revertable?.id && (
                <Button size="sm" onClick={() => setConfirming(m)}>
                  Switch back
                </Button>
              )}
            </div>
          </li>
        ))}
      </ul>
      {confirming && (
        <ConfirmDialog
          title="Switch back to the previous database?"
          body={
            <>
              This project will use {confirming.source_label} (
              <span className="font-mono text-xs break-all">
                {confirming.source_location}
              </span>
              ) again. Nothing is copied back: anything you&rsquo;ve added since
              the move stays in the other database.
            </>
          }
          confirmLabel="Switch back"
          isPending={revert.isPending}
          warning={revert.error ? errorMessage(revert.error) : undefined}
          onConfirm={() =>
            revert.mutate(confirming.id, {
              onSuccess: () => setConfirming(null),
            })
          }
          onClose={() => {
            revert.reset()
            setConfirming(null)
          }}
        />
      )}
    </>
  )
}
