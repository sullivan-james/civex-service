import type { AuditLogEntry } from '../../api/audit'
import type { SyncConflict } from '../../api/remote'
import { formatDate } from '../../lib/utils'
import {
  describeAttempt,
  kindLabel,
  settledLabel,
} from '../../utils/syncConflicts'
import { DiffValue } from '../sync/DiffValue'
import { Badge, Button } from '../ui'

/** What a kind of conflict is called on a history row. */
const SHORT: Record<string, string> = {
  conflict: 'Clashed',
  rejected: 'Refused',
  edit_vs_delete: 'Met a delete',
}

/** On a history row: that this change did not go in as made, and whether it still
 * needs someone. Nothing for a change that did. */
export function SyncBadge({ entry }: { entry: AuditLogEntry }) {
  const rows = entry.sync ?? []
  if (rows.length === 0) return null
  const open = rows.filter((c) => c.status === 'open')
  if (open.length === 0) return <Badge variant="default">Sync: settled</Badge>
  const kinds = [
    ...new Set(open.map((c) => SHORT[c.kind] ?? kindLabel(c.kind))),
  ]
  return (
    <Badge variant="attention">
      {kinds.join(', ')}
      {open.length > 1 ? ` · ${open.length}` : ''}
    </Badge>
  )
}

function Clash({ c }: { c: SyncConflict }) {
  return (
    <div className="space-y-2">
      <div className="grid gap-2 sm:grid-cols-2">
        <div className="min-w-0 rounded-md border border-accent-subtle-border bg-accent-subtle p-2 text-sm">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-fg-muted">
            Kept (theirs){c.theirs_actor ? ` · ${c.theirs_actor}` : ''}
          </div>
          <DiffValue
            value={c.theirs}
            other={c.yours}
            dtype={c.dtype}
            side="left"
          />
        </div>
        <div className="min-w-0 rounded-md border border-success-muted bg-success-subtle p-2 text-sm">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-fg-muted">
            Yours
          </div>
          <DiffValue
            value={c.yours}
            other={c.theirs}
            dtype={c.dtype}
            side="right"
          />
        </div>
      </div>
    </div>
  )
}

function Attempt({ c }: { c: SyncConflict }) {
  return (
    <div className="space-y-2">
      <p className="text-sm">{describeAttempt(c, formatDate)}</p>
      {c.changes.map((ch) => (
        <div key={ch.field_id} className="space-y-1">
          <div className="text-xs font-medium text-fg-muted">
            {ch.field_label}
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="min-w-0 rounded-md border border-accent-subtle-border bg-accent-subtle p-2 text-sm">
              <DiffValue
                value={ch.before}
                other={ch.after}
                dtype={ch.dtype}
                side="left"
              />
            </div>
            <div className="min-w-0 rounded-md border border-success-muted bg-success-subtle p-2 text-sm">
              <DiffValue
                value={ch.after}
                other={ch.before}
                dtype={ch.dtype}
                side="right"
              />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

/** In a history entry's window: for a change that did not go in as made, what
 * each side had (the same left and right as the merge view), why, and how it
 * ended, with a way into the record to settle it while it is open. */
export function SyncOutcome({ entry }: { entry: AuditLogEntry }) {
  const rows = entry.sync ?? []
  if (rows.length === 0) return null
  return (
    <section aria-label="What sync did with this change" className="space-y-3">
      <h3 className="text-sm font-medium">This change did not go in as made</h3>
      {rows.map((c) => (
        <div
          key={c.id}
          className="space-y-2 rounded-lg border border-attention-muted bg-canvas p-3"
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">
              {c.kind === 'conflict'
                ? (c.field_label ?? 'A field')
                : (SHORT[c.kind] ?? kindLabel(c.kind))}
            </span>
            {c.status === 'open' ? (
              <Badge variant="attention">Still to settle</Badge>
            ) : (
              <Badge variant="success">
                {settledLabel(c.resolution)}
                {c.resolved_at ? ` · ${formatDate(c.resolved_at)}` : ''}
              </Badge>
            )}
          </div>
          {c.kind === 'conflict' ? <Clash c={c} /> : <Attempt c={c} />}
          {c.status === 'open' &&
            c.entity_type === 'record' &&
            !c.record_deleted && (
              <Button
                size="sm"
                variant="primary"
                to={`/records/${c.entity_id}?tab=resolve`}
              >
                Resolve side by side
              </Button>
            )}
        </div>
      ))}
    </section>
  )
}
