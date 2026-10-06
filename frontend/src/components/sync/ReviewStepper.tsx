import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { useSyncConflicts } from '../../hooks/useRemote'
import {
  endReview,
  readReview,
  saveReview,
  stepsFrom,
  type ReviewStep,
} from '../../utils/reviewSession'
import { inReviewOrder } from '../../utils/syncConflicts'
import { Button } from '../ui'
import { StepBadge } from '../ui/StepBadge'

const at = (id: string) => `/records/${id}?tab=resolve`

function Steps({
  recordId,
  steps,
  stillOpen,
  onExit,
}: {
  recordId: string
  steps: ReviewStep[]
  /** The records that still have something to settle. */
  stillOpen: Set<string>
  onExit: () => void
}) {
  const index = steps.findIndex((s) => s.id === recordId)
  const left = steps.filter((s) => stillOpen.has(s.id)).length
  // The next one that still needs doing, after this and then from the start.
  const next =
    [...steps.slice(index + 1), ...steps.slice(0, index)].find(
      (s) => s.id !== recordId && stillOpen.has(s.id),
    ) ?? null

  return (
    <nav
      aria-label="Review progress"
      className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-border bg-canvas-subtle px-3 py-2"
    >
      <span className="text-sm font-medium">Reviewing sync changes</span>
      <ol className="flex max-w-full flex-1 items-center gap-1 overflow-x-auto py-1">
        {steps.map((s, i) => {
          const state =
            s.id === recordId
              ? 'current'
              : stillOpen.has(s.id)
                ? 'upcoming'
                : 'done'
          return (
            <li key={s.id} className="shrink-0">
              <Link
                to={at(s.id)}
                title={`${s.name}${state === 'done' ? ' (settled)' : ''}`}
                aria-label={`${s.name}, step ${i + 1} of ${steps.length}${state === 'done' ? ', settled' : ''}`}
                aria-current={state === 'current' ? 'step' : undefined}
                className="inline-flex rounded-full focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                <StepBadge index={i + 1} state={state} />
              </Link>
            </li>
          )
        })}
      </ol>
      <span className="text-sm text-fg-muted" aria-live="polite">
        {left === 0 ? 'All settled' : `${left} of ${steps.length} left`}
      </span>
      {next && (
        <Button size="sm" variant="primary" to={at(next.id)}>
          Next: {next.name}
        </Button>
      )}
      <Button size="sm" variant="link" onClick={onExit}>
        {left === 0 ? 'Finish' : 'Exit review'}
      </Button>
    </nav>
  )
}

/** Wraps a record page while someone is reviewing sync changes: every record that
 * had something to settle is a step, settled ones are ticked, and Next goes to
 * the next one still to do. It starts when the person opens a record's Resolve
 * tab or presses Start review, and ends with Exit review. */
export function ReviewStepper({
  recordId,
  active,
}: {
  recordId: string
  /** The person is on the Resolve tab, which starts a review if none is going. */
  active: boolean
}) {
  // Nothing is asked for unless a review is going or is being started here: a
  // record page of a project with no sync pays nothing for the stepper.
  const wanted = active || readReview() !== null
  const { data } = useSyncConflicts(wanted)
  if (!wanted || !Array.isArray(data)) return null
  return <Session recordId={recordId} active={active} conflicts={data} />
}

function Session({
  recordId,
  active,
  conflicts,
}: {
  recordId: string
  active: boolean
  conflicts: NonNullable<ReturnType<typeof useSyncConflicts>['data']>
}) {
  const [steps, setSteps] = useState<ReviewStep[] | null>(() => {
    const saved = readReview()
    if (saved?.some((s) => s.id === recordId)) return saved
    if (!active) return null
    const fresh = stepsFrom(inReviewOrder(conflicts))
    saveReview(fresh)
    return fresh
  })
  const stillOpen = useMemo(
    () => new Set(conflicts.map((c) => c.entity_id)),
    [conflicts],
  )
  if (!steps || !steps.some((s) => s.id === recordId)) return null
  return (
    <Steps
      recordId={recordId}
      steps={steps}
      stillOpen={stillOpen}
      onExit={() => {
        endReview()
        setSteps(null)
      }}
    />
  )
}
