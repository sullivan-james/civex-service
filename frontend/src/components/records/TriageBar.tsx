import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import type { CivexRecord } from '../../api/records'
import type { Field as SchemaField } from '../../api/schemas'
import { useUpdateRecord } from '../../hooks/useRecords'
import { errorMessage } from '../../lib/errors'
import { displayLabel } from '../../utils/naming'
import {
  markReviewed,
  positionOf,
  readSession,
  rememberReviewedField,
  reviewedField,
  triagePath,
  type TriageSession,
} from '../../utils/triage'
import { Button, Select } from '../ui'
import { Check, ChevronLeft, ChevronRight, SkipForward } from '../ui/icons'

function load(sessionId: string | null): TriageSession | null {
  try {
    return readSession(sessionStorage, sessionId)
  } catch {
    return null
  }
}

/** The "working through" strip on a record opened from a list: where you are
 * in it, Previous/Next, and "Mark reviewed & next". Renders nothing for a
 * record that wasn't opened as part of a list. */
export function TriageBar({
  sessionId,
  record,
  fields,
}: {
  sessionId: string | null
  record: CivexRecord
  fields: SchemaField[]
}) {
  const navigate = useNavigate()
  // quiet: a failure shows in the bar, not as a toast over the page
  const update = useUpdateRecord({ quiet: true })
  const [session, setSession] = useState(() => load(sessionId))
  const [seenId, setSeenId] = useState(sessionId)
  const [chosenField, setChosenField] = useState<string | null>(null)
  if (sessionId !== seenId) {
    setSeenId(sessionId)
    setSession(load(sessionId))
  }

  const position = session ? positionOf(session, record.id) : null
  if (!session || !position) return null

  const booleans = fields.filter((f) => f.type === 'boolean')
  const field =
    chosenField && booleans.some((f) => f.name === chosenField)
      ? chosenField
      : reviewedField(localStorage, record.schema_name, fields)
  const alreadyReviewed = field ? record.data[field] === true : false
  const isReviewed = alreadyReviewed || session.reviewed.includes(record.id)
  const done = position.index === position.total

  const go = (id: string) => navigate(triagePath(id, session.id))

  function advance() {
    if (position!.nextId) go(position!.nextId)
  }

  function markAndNext() {
    if (!field) return
    const finish = () => {
      setSession(markReviewed(sessionStorage, session!, record.id))
      advance()
    }
    if (alreadyReviewed) return finish()
    update.mutate(
      { id: record.id, data: { ...record.data, [field]: true } },
      { onSuccess: finish },
    )
  }

  const progress = Math.round((position.index / position.total) * 100)

  return (
    <section
      aria-label="Triage"
      className="sticky top-0 z-10 -mx-1 rounded-md border border-border bg-canvas-subtle px-4 py-3 shadow-sm"
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="min-w-0 text-sm text-fg-muted">
          Working through{' '}
          <span className="font-medium text-fg">{session.label}</span>
        </p>
        <div className="flex items-center gap-1">
          {position.previousId ? (
            <Link
              to={triagePath(position.previousId, session.id)}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-sm text-accent hover:bg-accent-subtle"
            >
              <ChevronLeft size={14} aria-hidden="true" /> Previous
            </Link>
          ) : (
            <span className="inline-flex items-center gap-1 px-2 py-1 text-sm text-fg-subtle">
              <ChevronLeft size={14} aria-hidden="true" /> Previous
            </span>
          )}
          <span className="px-2 text-sm font-medium tabular-nums text-fg">
            {position.index} of {position.total}
          </span>
          {position.nextId ? (
            <Link
              to={triagePath(position.nextId, session.id)}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-sm text-accent hover:bg-accent-subtle"
            >
              Next <ChevronRight size={14} aria-hidden="true" />
            </Link>
          ) : (
            <span className="inline-flex items-center gap-1 px-2 py-1 text-sm text-fg-subtle">
              Next <ChevronRight size={14} aria-hidden="true" />
            </span>
          )}
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {isReviewed && (
            <span className="text-xs font-medium text-success">Reviewed</span>
          )}
          <span
            className="text-xs text-fg-muted tabular-nums"
            aria-live="polite"
          >
            {session.reviewed.length} reviewed this session
          </span>
          {booleans.length > 1 && field && (
            <Select
              size="sm"
              aria-label="Field that marks a record reviewed"
              value={field}
              onChange={(e) => {
                rememberReviewedField(
                  localStorage,
                  record.schema_name,
                  e.target.value,
                )
                setChosenField(e.target.value)
              }}
            >
              {booleans.map((f) => (
                <option key={f.name} value={f.name}>
                  {displayLabel(f.name, f.label)}
                </option>
              ))}
            </Select>
          )}
          <Button
            size="sm"
            onClick={advance}
            disabled={!position.nextId}
            title={position.nextId ? undefined : 'This is the last record'}
          >
            <SkipForward size={14} /> Skip
          </Button>
          <Button
            size="sm"
            variant="primary"
            onClick={markAndNext}
            disabled={!field || update.isPending}
            title={
              field
                ? undefined
                : 'Add a yes/no field to this schema to mark records reviewed'
            }
          >
            <Check size={14} />
            {update.isPending
              ? 'Saving…'
              : done
                ? 'Mark reviewed'
                : 'Mark reviewed & next'}
          </Button>
        </div>
      </div>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={position.total}
        aria-valuenow={position.index}
        aria-label="Position in list"
        className="mt-3 h-1 overflow-hidden rounded-full bg-canvas-inset"
      >
        <div className="h-full bg-accent" style={{ width: `${progress}%` }} />
      </div>
      {update.error != null && (
        <p role="alert" className="mt-2 text-xs text-danger">
          {errorMessage(update.error)}
        </p>
      )}
      {!field && (
        <p className="mt-2 text-xs text-fg-muted">
          This schema has no yes/no field, so there is nothing to mark. Skip and
          Next still work.
        </p>
      )}
    </section>
  )
}
