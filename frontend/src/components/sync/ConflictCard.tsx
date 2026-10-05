import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import type { ConflictTake, SyncConflict } from '../../api/remote'
import { useResolveConflict } from '../../hooks/useRemote'
import { errorMessage } from '../../lib/errors'
import { formatDate } from '../../lib/utils'
import { AuditValue } from '../audit/AuditValue'
import { takeLabel } from '../../utils/syncConflicts'
import { Badge, Button, Disclosure, Input } from '../ui'

/** A field a person can retype here; anything else is chosen from the two sides. */
const RETYPABLE = new Set(['string', 'longtext', 'url', 'integer', 'float'])

/** Who and when, as it reads under a value: "Dana · 5 Oct". */
function by(actor: string | null, at: string | null): string | null {
  const parts = [actor, at ? formatDate(at) : null].filter(Boolean)
  return parts.length ? parts.join(' · ') : null
}

function Side({
  title,
  note,
  value,
  dtype,
}: {
  title: string
  note?: string | null
  value: unknown
  dtype: string | null
}) {
  return (
    <div className="min-w-0 space-y-1">
      <div className="text-xs font-medium text-fg-muted">
        {title}
        {note && <span className="font-normal"> · {note}</span>}
      </div>
      <div className="break-words rounded-md border border-border bg-canvas-subtle px-2 py-1 text-sm">
        <AuditValue value={value} dtype={dtype} />
      </div>
    </div>
  )
}

/** The record a conflict is about, as a person knows it: its name, where it is,
 * and a link, instead of an id. */
export function ConflictSubject({ conflict: c }: { conflict: SyncConflict }) {
  const name = c.record_name ?? `${c.entity_type} ${c.entity_id.slice(0, 8)}`
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      {c.entity_type === 'record' ? (
        <Link to={`/records/${c.entity_id}`} className="font-medium">
          {name}
        </Link>
      ) : (
        <span className="font-medium">{name}</span>
      )}
      {c.schema_name && <Badge variant="accent">{c.schema_name}</Badge>}
      {c.dataset_name && (
        <span className="text-xs text-fg-muted">in {c.dataset_name}</span>
      )}
      {c.record_deleted && <Badge variant="attention">deleted</Badge>}
    </span>
  )
}

/** One thing that did not go in as made, with what is needed to judge it and the
 * ways to settle it. The one view of a conflict: the record page shows it inline
 * and the review page shows it one at a time. */
export function ConflictCard({
  conflict: c,
  hideRecord = false,
  shortcuts = false,
  onResolved,
}: {
  conflict: SyncConflict
  /** The page is already about this record. */
  hideRecord?: boolean
  /** `1` and `2` take the first two choices shown (keep theirs; use mine, delete
   * or send again), for stepping through many without the mouse. */
  shortcuts?: boolean
  onResolved?: () => void
}) {
  const resolve = useResolveConflict()
  const [typing, setTyping] = useState<string | null>(null)

  const act = (
    take: ConflictTake,
    extra: { value?: unknown; force?: boolean } = {},
  ) => resolve.mutate({ id: c.id, take, ...extra }, { onSuccess: onResolved })

  const typed = (text: string): unknown =>
    c.dtype === 'integer' || c.dtype === 'float' ? Number(text) : text
  const canRetype = c.takes.includes('value') && RETYPABLE.has(c.dtype ?? '')
  const label = (t: ConflictTake) => takeLabel(c.kind, t)
  const busy = resolve.isPending
  const choices = c.takes.filter((t) => t !== 'value')

  useEffect(() => {
    if (!shortcuts || busy || typing !== null) return
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (el?.closest('input, textarea, select, [contenteditable="true"]'))
        return
      const take =
        e.key === '1' ? choices[0] : e.key === '2' ? choices[1] : undefined
      if (!take) return
      e.preventDefault()
      act(take, take === 'mine' ? { force: c.stale } : {})
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shortcuts, busy, typing, c.id, c.stale, c.takes.join()])

  return (
    <article
      aria-label={`${c.field_label ?? c.kind} on ${c.record_name ?? c.entity_type}`}
      className="space-y-3 rounded-lg border border-border bg-canvas p-3"
    >
      {!hideRecord && <ConflictSubject conflict={c} />}

      {c.kind === 'conflict' && (
        <>
          <p className="text-sm">
            <span className="font-medium">{c.field_label ?? c.field}</span> was
            changed on both sides. Theirs was kept; yours is saved here.
          </p>
          <div className="grid gap-2 sm:grid-cols-3">
            <Side title="Before" value={c.base} dtype={c.dtype} />
            <Side
              title="Kept"
              note={by(c.theirs_actor, c.theirs_at)}
              value={c.theirs}
              dtype={c.dtype}
            />
            <Side title="Yours" value={c.yours} dtype={c.dtype} />
          </div>
          {c.stale && (
            <p
              role="status"
              className="rounded-md border border-attention-muted bg-attention-subtle px-2 py-1 text-sm text-attention"
            >
              It has changed again since, and is now{' '}
              <AuditValue value={c.current} dtype={c.dtype} />. Using yours
              would overwrite that.
            </p>
          )}
          {c.also_saved.length > 0 && (
            <Disclosure
              summary={`${c.also_saved.length} other value${
                c.also_saved.length === 1 ? '' : 's'
              } from the same edit went in`}
            >
              <ul className="space-y-1 px-3 py-2 text-sm">
                {c.also_saved.map((a) => (
                  <li key={a.field_label}>
                    <span className="text-fg-muted">{a.field_label}: </span>
                    <AuditValue value={a.value} compact />
                  </li>
                ))}
              </ul>
            </Disclosure>
          )}
        </>
      )}

      {c.kind !== 'conflict' && (
        <p className="text-sm">
          {c.message ??
            (c.kind === 'rejected'
              ? 'The server did not accept this change.'
              : 'This could not be applied.')}
          {c.kind === 'rejected' && (
            <span className="block text-xs text-fg-muted">
              Your change is saved on this device only. Put the cause right,
              then send it again.
            </span>
          )}
          {c.theirs_actor && (
            <span className="block text-xs text-fg-muted">
              Last changed by {by(c.theirs_actor, c.theirs_at)}
            </span>
          )}
        </p>
      )}

      {typing !== null ? (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            act('value', { value: typed(typing), force: true })
          }}
        >
          <Input
            aria-label={`New value for ${c.field_label ?? 'the field'}`}
            value={typing}
            onChange={(e) => setTyping(e.target.value)}
            autoFocus
            className="min-w-0 flex-1"
          />
          <Button type="submit" size="sm" variant="primary" disabled={busy}>
            Save
          </Button>
          <Button type="button" size="sm" onClick={() => setTyping(null)}>
            Cancel
          </Button>
        </form>
      ) : (
        <div className="flex flex-wrap gap-2">
          {choices.map((t) => (
            <Button
              key={t}
              size="sm"
              variant={
                t === 'theirs'
                  ? 'default'
                  : t === 'delete'
                    ? 'danger'
                    : 'primary'
              }
              disabled={busy}
              onClick={() => act(t, t === 'mine' ? { force: c.stale } : {})}
            >
              {t === 'mine' && c.stale ? 'Use mine anyway' : label(t)}
            </Button>
          ))}
          {canRetype && (
            <Button
              size="sm"
              disabled={busy}
              onClick={() => setTyping(String(c.current ?? c.yours ?? ''))}
            >
              {label('value')}
            </Button>
          )}
          {c.kind === 'rejected' && c.record_name && !c.record_deleted && (
            <Button size="sm" variant="link" to={`/records/${c.entity_id}`}>
              Open record
            </Button>
          )}
        </div>
      )}

      {resolve.error && (
        <p role="alert" className="text-xs text-danger">
          {errorMessage(resolve.error)}
        </p>
      )}
    </article>
  )
}
