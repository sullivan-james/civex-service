import { useMemo, type ReactNode } from 'react'
import type { ConflictTake, SyncConflict } from '../../api/remote'
import type { Field } from '../../api/schemas'
import {
  useReopenConflicts,
  useResolveConflict,
  useResolveMany,
  useSyncConflicts,
} from '../../hooks/useRemote'
import { errorMessage } from '../../lib/errors'
import { formatDate } from '../../lib/utils'
import {
  buildMerge,
  type MergeRow,
  type MergeSection,
} from '../../utils/syncMerge'
import {
  describeAttempt,
  inReviewOrder,
  settledLabel,
  takeLabel,
} from '../../utils/syncConflicts'
import { summarise } from '../../utils/restrictions'
import { AuditValue } from '../audit/AuditValue'
import { EditableValue } from '../records/RecordFieldGrid'
import { Badge, Button, EmptyState } from '../ui'
import { DiffValue } from './DiffValue'

/** A column's title, and a title the narrow layout shows in each cell instead. */
function Title({ children }: { children: ReactNode }) {
  return (
    <div className="text-xs font-semibold uppercase tracking-wide text-fg-muted">
      {children}
    </div>
  )
}

function Headers({ left, right }: { left: string; right: string }) {
  return (
    <div className="hidden gap-3 px-1 md:grid md:grid-cols-3">
      <Title>{left}</Title>
      <Title>Result (what this record is now)</Title>
      <Title>{right}</Title>
    </div>
  )
}

function Row({
  row,
  field,
  value,
  leftTitle,
  rightTitle,
  referenceLabels,
  referenceCollections,
  onSave,
}: {
  row: MergeRow
  field: Field | undefined
  value: unknown
  leftTitle: string
  rightTitle: string
  referenceLabels?: Record<string, string | null> | null
  referenceCollections?: Record<string, string> | null
  onSave: (name: string, value: unknown | undefined) => void
}) {
  const resolve = useResolveConflict()
  const reopen = useReopenConflicts()
  const c = row.conflict
  const clash = c.kind === 'conflict'
  const open = c.status === 'open'
  const busy = resolve.isPending || reopen.isPending
  const failure = resolve.error ?? reopen.error

  return (
    <div
      role="group"
      aria-label={row.label}
      className={`space-y-2 rounded-lg border border-border bg-canvas p-2 ${open ? '' : 'opacity-75'}`}
    >
      <div className="flex flex-wrap items-baseline gap-2 px-1">
        <span className="font-medium">{row.label}</span>
        {clash && row.base !== undefined && row.base !== null && (
          <span className="text-xs text-fg-muted">
            Before either of you:{' '}
            <AuditValue value={row.base} dtype={row.dtype} compact />
          </span>
        )}
        {!open && <Badge variant="success">{settledLabel(row.settled)}</Badge>}
        {row.settled === 'theirs' && (
          <Button
            size="sm"
            variant="link"
            disabled={busy}
            onClick={() => reopen.mutate([c.id])}
          >
            Undo
          </Button>
        )}
      </div>
      <div className="grid gap-2 md:grid-cols-3">
        <div className="min-w-0 space-y-2 rounded-md border border-accent-subtle-border bg-accent-subtle p-2">
          <div className="md:hidden">
            <Title>{leftTitle}</Title>
          </div>
          <div className="text-sm">
            <DiffValue
              value={row.left}
              other={row.right}
              dtype={row.dtype}
              side="left"
            />
          </div>
          {clash && open && (
            <Button
              size="sm"
              disabled={busy}
              onClick={() => resolve.mutate({ id: c.id, take: 'theirs' })}
            >
              Accept theirs
            </Button>
          )}
        </div>

        <div className="min-w-0 space-y-1 rounded-md border border-border bg-canvas-subtle p-2">
          <div className="md:hidden">
            <Title>Result (what this record is now)</Title>
          </div>
          <div className="text-sm">
            {field ? (
              <EditableValue
                field={field}
                value={value}
                referenceLabels={referenceLabels}
                referenceCollections={referenceCollections}
                onSave={(v) => onSave(field.name, v)}
              />
            ) : (
              <span className="text-fg-muted">
                That field has been removed, so there is nothing to edit.
              </span>
            )}
          </div>
          {!clash && open && field && (
            <p className="text-xs text-fg-muted">
              Click the value to fix it, then send it again above.
            </p>
          )}
        </div>

        <div className="min-w-0 space-y-2 rounded-md border border-success-muted bg-success-subtle p-2">
          <div className="md:hidden">
            <Title>{rightTitle}</Title>
          </div>
          <div className="text-sm">
            <DiffValue
              value={row.right}
              other={row.left}
              dtype={row.dtype}
              side="right"
            />
          </div>
          {clash && open && c.takes.includes('mine') && (
            <Button
              size="sm"
              variant="primary"
              disabled={busy}
              onClick={() =>
                resolve.mutate({ id: c.id, take: 'mine', force: c.stale })
              }
            >
              {c.stale ? 'Accept yours anyway' : 'Accept yours'}
            </Button>
          )}
        </div>
      </div>
      {clash && open && c.stale && (
        <p role="status" className="px-1 text-xs text-attention">
          The result has changed again since this was recorded. Accepting yours
          would overwrite it.
        </p>
      )}
      {failure && (
        <p role="alert" className="px-1 text-xs text-danger">
          {errorMessage(failure)}
        </p>
      )}
    </div>
  )
}

/** A record (or a change to one) the server refused: not a clash between two
 * values, so no sides. The reason, the field it names, editable here with what
 * it allows (saving sends the record again by itself), and the other choices. */
function RefusedFix({
  conflict: c,
  fields,
  data,
  referenceLabels,
  referenceCollections,
  onSave,
}: {
  conflict: SyncConflict
  fields: Field[]
  data: Record<string, unknown>
  referenceLabels?: Record<string, string | null> | null
  referenceCollections?: Record<string, string> | null
  onSave: (name: string, value: unknown | undefined) => void
}) {
  const resolve = useResolveConflict()
  const open = c.status === 'open'
  const sending = open && c.resolution === 'retrying'
  const named = c.field?.startsWith('data.')
    ? fields.find((f) => f.id === c.field!.slice(5))
    : undefined
  const changed = (c.changes ?? [])
    .map((ch) => fields.find((f) => f.name === ch.field_name))
    .filter((f): f is Field => f !== undefined)
  const shown = named ? [named] : changed
  return (
    <div className="space-y-3 rounded-lg border border-attention-muted bg-attention-subtle p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-medium">
          {c.attempted === 'create'
            ? 'Not on the server yet'
            : 'Your change was not taken'}
        </h2>
        {sending && <Badge variant="accent">Sending again…</Badge>}
        {!open && <Badge variant="success">{settledLabel(c.resolution)}</Badge>}
      </div>
      <p className="text-sm">
        The server refused it: {c.message ?? 'no reason was given'}
      </p>
      {open && shown.length > 0 && (
        <div className="space-y-2">
          {shown.map((f) => {
            const rules = summarise(f.restrictions, f.type)
            return (
              <div
                key={f.id}
                className="grid gap-1 rounded-md border border-border bg-canvas p-2 md:grid-cols-[12rem_1fr]"
              >
                <div className="text-sm font-medium">
                  {f.label ?? f.name}
                  {rules && (
                    <div className="text-xs font-normal text-fg-muted">
                      Allowed: {rules.replace(/^choices: /, '')}
                    </div>
                  )}
                </div>
                <div className="text-sm">
                  <EditableValue
                    field={f}
                    value={data[f.name]}
                    referenceLabels={referenceLabels}
                    referenceCollections={referenceCollections}
                    onSave={(v) => onSave(f.name, v)}
                  />
                </div>
              </div>
            )
          })}
        </div>
      )}
      {open && !sending && (c.sits_under ?? []).length > 0 && (
        <p className="text-sm">
          It sits under{' '}
          {(c.sits_under ?? [])
            .map((u) => `${u.schema_name} ${u.name ?? ''}`.trim())
            .join(' › ')}
          , which is deleted here too: the server won&apos;t take it until that
          is back.
        </p>
      )}
      {open && (
        <div className="flex flex-wrap items-center gap-2">
          {!sending && c.takes.includes('restore_above') && (
            <Button
              size="sm"
              variant="primary"
              disabled={resolve.isPending}
              onClick={() =>
                resolve.mutate({ id: c.id, take: 'restore_above' })
              }
            >
              Restore{' '}
              {(c.sits_under ?? [])
                .map((u) => u.name ?? u.schema_name)
                .join(' › ')}{' '}
              and send
            </Button>
          )}
          {!sending && c.takes.includes('retry') && (
            <Button
              size="sm"
              disabled={resolve.isPending}
              onClick={() => resolve.mutate({ id: c.id, take: 'retry' })}
            >
              Send unchanged
            </Button>
          )}
          <Button
            size="sm"
            disabled={resolve.isPending}
            onClick={() => resolve.mutate({ id: c.id, take: 'theirs' })}
          >
            {c.attempted === 'create'
              ? 'Keep it on this device only'
              : 'Let it go'}
          </Button>
        </div>
      )}
      {resolve.error && (
        <p role="alert" className="text-xs text-danger">
          {errorMessage(resolve.error)}
        </p>
      )}
    </div>
  )
}

function AttemptHeader({ conflict: c }: { conflict: SyncConflict }) {
  const resolve = useResolveConflict()
  const open = c.status === 'open'
  const choices = c.takes.filter((t) => t !== 'value' && t !== 'edited')
  return (
    <div className="space-y-2 rounded-lg border border-attention-muted bg-attention-subtle p-3">
      <p className="text-sm">{describeAttempt(c, formatDate)}</p>
      {open ? (
        <div className="flex flex-wrap items-center gap-2">
          {c.kind === 'rejected' && c.attempted !== 'delete' && (
            <span className="text-xs text-fg-muted">Or:</span>
          )}
          {choices.map((t: ConflictTake) => (
            <Button
              key={t}
              size="sm"
              variant={
                t === 'delete'
                  ? 'danger'
                  : t === 'theirs'
                    ? 'default'
                    : 'primary'
              }
              disabled={resolve.isPending}
              onClick={() => resolve.mutate({ id: c.id, take: t })}
            >
              {takeLabel(c.kind, t)}
            </Button>
          ))}
        </div>
      ) : (
        <Badge variant="success">{settledLabel(c.resolution)}</Badge>
      )}
      {resolve.error && (
        <p role="alert" className="text-xs text-danger">
          {errorMessage(resolve.error)}
        </p>
      )}
    </div>
  )
}

function ClashBulk({ recordId, open }: { recordId: string; open: number }) {
  const bulk = useResolveMany()
  if (open < 2) return null
  const run = (take: 'theirs' | 'mine') =>
    bulk.mutate({ take, kind: 'conflict', record_id: recordId })
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button size="sm" disabled={bulk.isPending} onClick={() => run('theirs')}>
        Accept all theirs
      </Button>
      <Button
        size="sm"
        variant="primary"
        disabled={bulk.isPending}
        onClick={() => run('mine')}
      >
        Accept all yours
      </Button>
      {bulk.data && bulk.data.failed.length > 0 && (
        <span role="alert" className="text-xs text-danger">
          {bulk.data.failed.length} stay open: {bulk.data.failed[0].message}
        </span>
      )}
      {bulk.error && (
        <span role="alert" className="text-xs text-danger">
          {errorMessage(bulk.error)}
        </span>
      )}
    </div>
  )
}

/** A merge editor for one record, like a version-control merge: what the other
 * side has on the left, this device's on the right, and what the record is now in
 * the middle, with what differs marked. Accept either side per field (or for all),
 * or edit the result itself. A refused change or an edit against a delete has its
 * own block, with the reason and its choices. Everything here is the record's own
 * values, so every type is edited by the same inputs as on the Fields tab. */
export function MergeView({
  recordId,
  fields,
  data,
  conflicts,
  referenceLabels,
  referenceCollections,
  onSave,
  onClose,
}: {
  recordId: string
  fields: Field[]
  data: Record<string, unknown>
  /** Open ones, and those settled since the page opened. */
  conflicts: SyncConflict[]
  referenceLabels?: Record<string, string | null> | null
  referenceCollections?: Record<string, string> | null
  onSave: (name: string, value: unknown | undefined) => void
  onClose: () => void
}) {
  const merge = useMemo(
    () => buildMerge(conflicts, fields),
    [conflicts, fields],
  )
  const { data: all } = useSyncConflicts(true)
  const byName = useMemo(
    () => new Map(fields.map((f) => [f.name, f])),
    [fields],
  )

  // The records that have something to settle, for stepping between them.
  const records = useMemo(() => {
    const seen: string[] = []
    for (const c of inReviewOrder(all ?? []))
      if (!seen.includes(c.entity_id)) seen.push(c.entity_id)
    return seen
  }, [all])
  const at = records.indexOf(recordId)
  const prev = at > 0 ? records[at - 1] : null
  const next = at >= 0 && at < records.length - 1 ? records[at + 1] : null
  const there = (id: string) => `/records/${id}?tab=resolve`

  if (merge.total === 0)
    return (
      <EmptyState
        title="Nothing to settle on this record"
        message="Everything on it went in as it was made."
        action={<Button onClick={onClose}>Back to fields</Button>}
      />
    )

  const section = (s: MergeSection, i: number) => {
    const attempt = s.kind === 'attempt'
    if (
      attempt &&
      s.conflict.kind === 'rejected' &&
      s.conflict.attempted !== 'delete'
    )
      return (
        <section
          key={s.conflict.id}
          aria-label="Refused by the server"
          className="space-y-2"
        >
          <RefusedFix
            conflict={s.conflict}
            fields={fields}
            data={data}
            referenceLabels={referenceLabels}
            referenceCollections={referenceCollections}
            onSave={onSave}
          />
          {i < merge.sections.length - 1 && <hr className="border-border" />}
        </section>
      )
    const left = attempt ? 'Before your change' : 'Kept (theirs)'
    const right = attempt ? 'Your change' : 'Yours'
    return (
      <section
        key={attempt ? s.conflict.id : 'clashes'}
        aria-label={attempt ? 'Change not applied' : 'Changed on both sides'}
        className="space-y-2"
      >
        {attempt ? (
          <AttemptHeader conflict={s.conflict} />
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-medium">
              Changed on both sides
              <span className="ml-2 font-normal text-fg-muted">
                The other side’s value was kept; yours is saved here.
              </span>
            </h2>
            <ClashBulk
              recordId={recordId}
              open={s.rows.filter((r) => r.conflict.status === 'open').length}
            />
          </div>
        )}
        {s.rows.length > 0 && <Headers left={left} right={right} />}
        {s.rows.map((row) => {
          const field = row.fieldName ? byName.get(row.fieldName) : undefined
          return (
            <Row
              key={row.key}
              row={row}
              field={field}
              value={field ? data[field.name] : undefined}
              leftTitle={left}
              rightTitle={right}
              referenceLabels={referenceLabels}
              referenceCollections={referenceCollections}
              onSave={onSave}
            />
          )
        })}
        {/* Sections are told apart by their own headings. */}
        {i < merge.sections.length - 1 && <hr className="border-border" />}
      </section>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm text-fg-muted" aria-live="polite">
          {merge.open === 0
            ? 'All settled'
            : `${merge.open} of ${merge.total} left to settle`}
        </span>
        <span className="flex flex-wrap items-center gap-2 text-xs">
          {records.length > 1 && at >= 0 && (
            <span className="text-fg-muted">
              Record {at + 1} of {records.length} with changes to review
            </span>
          )}
          {prev && (
            <Button size="sm" to={there(prev)}>
              Previous record
            </Button>
          )}
          {next && (
            <Button size="sm" to={there(next)}>
              Next record
            </Button>
          )}
        </span>
      </div>

      {merge.open === 0 && (
        <div
          role="status"
          className="flex flex-wrap items-center gap-3 rounded-lg border border-success-muted bg-success-subtle p-3 text-sm"
        >
          <span>Everything on this record is settled.</span>
          {next ? (
            <Button size="sm" variant="primary" to={there(next)}>
              Next record
            </Button>
          ) : (
            <Button size="sm" onClick={onClose}>
              Back to fields
            </Button>
          )}
        </div>
      )}

      {merge.sections.map(section)}
    </div>
  )
}
