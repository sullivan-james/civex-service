import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  Button,
  InfoTip,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Stepper,
  ProgressBar,
} from '../../ui'
import {
  useCancelMove,
  useMoveJob,
  usePreflightMove,
  useStartMove,
} from '../../../hooks/useDb'
import type { DatabaseSummary } from '../../../api/db'
import { errorMessage } from '../../../lib/errors'
import {
  formatDuration,
  formatEstimate,
  formatSize,
} from '../../../utils/dbFormat'
import { DestinationStep } from './DestinationStep'
import {
  EMPTY_DESTINATION,
  destinationReady,
  toTarget,
  type Destination,
} from './destination'

type Step = 'where' | 'review' | 'moving' | 'done'
const STEPS = [
  { label: 'Where to' },
  { label: 'Review' },
  { label: 'Moving' },
  { label: 'Done' },
]
const ORDER: Step[] = ['where', 'review', 'moving', 'done']

function DatabaseCard({
  heading,
  db,
}: {
  heading: string
  db: DatabaseSummary
}) {
  return (
    <div className="rounded-md border border-border bg-canvas p-3 min-w-0">
      <p className="text-xs text-fg-muted">{heading}</p>
      <p className="text-sm font-medium text-fg">{db.label}</p>
      <p
        className="text-xs font-mono text-fg-muted truncate"
        title={db.location}
      >
        {db.location}
      </p>
      {db.reachable && (
        <p className="text-xs text-fg-muted mt-1">
          {db.records.toLocaleString()} records · {formatSize(db.size_bytes)}
        </p>
      )}
    </div>
  )
}

/** Moves the project's data to another database, a step at a time: pick the
 * destination, review what will happen, watch it run, see it was checked. The
 * original database is never touched, which the wizard says at each step. */
export function MoveDatabaseWizard({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [chosenStep, setStep] = useState<Step>('where')
  const [dest, setDest] = useState<Destination>(EMPTY_DESTINATION)
  const [jobId, setJobId] = useState<string | null>(null)

  const preflight = usePreflightMove()
  const start = useStartMove()
  const cancel = useCancelMove()
  const job = useMoveJob(jobId)

  const check = preflight.data
  const state = job.data

  // Once the job has ended the wizard is on its last step, whatever step it
  // last set itself: the step follows from what the server says.
  const step: Step =
    chosenStep === 'moving' && state && state.status !== 'running'
      ? 'done'
      : chosenStep
  const moved = step === 'done' && state?.status === 'done'

  // After a successful move everything the app has cached came from the old
  // database, so refresh all of it.
  useEffect(() => {
    if (moved) qc.invalidateQueries()
  }, [moved, qc])

  const running = step === 'moving'

  return (
    <Modal onClose={onClose} size="lg" dismissible={!running}>
      <ModalHeader onClose={running ? undefined : onClose}>
        Move database
      </ModalHeader>
      <ModalBody className="space-y-5">
        <Stepper steps={STEPS} activeIndex={ORDER.indexOf(step)} />

        {step === 'where' && (
          <DestinationStep value={dest} onChange={setDest} />
        )}

        {step === 'review' && check && (
          <div className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <DatabaseCard heading="From (now in use)" db={check.source} />
              <DatabaseCard heading="To" db={check.target} />
            </div>
            {check.problems.map((p) => (
              <p
                key={p}
                role="alert"
                className="text-sm text-danger bg-danger-subtle border border-danger-muted rounded-md px-3 py-2"
              >
                {p}
              </p>
            ))}
            {check.warnings.map((w) => (
              <p key={w} className="text-sm text-fg-muted">
                {w}
              </p>
            ))}
            {check.can_proceed && (
              <p className="flex items-center gap-1 text-sm text-fg">
                Takes {formatEstimate(check.estimate_seconds)}
                <InfoTip>
                  Your data is copied, then checked against the original. Only
                  if the check passes does this project switch to the new
                  database. The original is left as it is, so you can switch
                  back. Uploaded files are stored separately and aren&rsquo;t
                  affected.
                </InfoTip>
              </p>
            )}
            {start.error && (
              <p role="alert" className="text-sm text-danger">
                {errorMessage(start.error)}
              </p>
            )}
          </div>
        )}

        {step === 'moving' && (
          <div className="space-y-3" aria-live="polite">
            {(() => {
              const p = state?.progress
              const pct =
                p && p.rows_total > 0
                  ? Math.min(
                      100,
                      Math.round((p.rows_done / p.rows_total) * 100),
                    )
                  : 0
              return (
                <>
                  <p className="text-sm text-fg">{p?.message || 'Starting…'}</p>
                  <ProgressBar
                    fraction={pct / 100}
                    label="Move progress"
                    className="w-full"
                  />
                  <p className="text-xs text-fg-muted">
                    {(p?.rows_done ?? 0).toLocaleString()} of{' '}
                    {(p?.rows_total ?? 0).toLocaleString()} rows ·{' '}
                    {p?.tables_done ?? 0} of {p?.tables_total ?? 0} tables
                  </p>
                  {job.error && (
                    <p role="alert" className="text-sm text-danger">
                      Lost contact with the server. Check{' '}
                      <span className="font-medium">Move history</span> in a
                      moment to see how it ended.
                    </p>
                  )}
                </>
              )
            })()}
          </div>
        )}

        {step === 'done' && state && (
          <div className="space-y-3">
            {state.status === 'done' && state.record ? (
              <>
                <p className="text-sm font-medium text-success">
                  Your data is now in {state.record.target_label}.
                </p>
                <p className="text-sm text-fg">
                  {Object.values(state.record.counts)
                    .reduce((a, b) => a + b, 0)
                    .toLocaleString()}{' '}
                  rows moved in {formatDuration(state.record.seconds)}, and
                  checked against the original.
                </p>
                <p className="flex items-center gap-1 break-all text-xs text-fg-muted">
                  {state.record.target_location}
                  <InfoTip>
                    The original is untouched at {state.record.source_location}.
                    You can switch back from the History tab.
                  </InfoTip>
                </p>
              </>
            ) : (
              <>
                <p role="alert" className="text-sm font-medium text-danger">
                  {state.status === 'cancelled'
                    ? 'Cancelled.'
                    : 'The move didn’t finish.'}
                </p>
                {state.error && (
                  <p className="text-sm text-fg">{state.error}</p>
                )}
                {state.record?.problems.map((p) => (
                  <p key={p} className="text-xs text-danger">
                    {p}
                  </p>
                ))}
                <p className="text-sm text-fg">
                  Nothing was changed: this project still uses its current
                  database.
                </p>
              </>
            )}
          </div>
        )}
      </ModalBody>
      <ModalFooter>
        {step === 'where' && (
          <>
            <Button onClick={onClose}>Cancel</Button>
            <Button
              variant="primary"
              disabled={!destinationReady(dest) || preflight.isPending}
              onClick={() =>
                preflight.mutate(toTarget(dest), {
                  onSuccess: () => setStep('review'),
                })
              }
            >
              {preflight.isPending ? 'Checking…' : 'Next'}
            </Button>
          </>
        )}
        {step === 'review' && (
          <>
            <Button
              onClick={() => {
                start.reset()
                setStep('where')
              }}
            >
              Back
            </Button>
            <Button
              variant="primary"
              disabled={!check?.can_proceed || start.isPending}
              onClick={() =>
                start.mutate(toTarget(dest), {
                  onSuccess: (j) => {
                    setJobId(j.id)
                    setStep('moving')
                  },
                })
              }
            >
              {start.isPending ? 'Starting…' : 'Move my data'}
            </Button>
          </>
        )}
        {step === 'moving' && (
          <Button
            onClick={() => jobId && cancel.mutate(jobId)}
            disabled={cancel.isPending || !jobId}
          >
            {cancel.isPending ? 'Cancelling…' : 'Cancel move'}
          </Button>
        )}
        {step === 'done' && (
          <>
            {state?.status !== 'done' && (
              <Button
                onClick={() => {
                  setJobId(null)
                  start.reset()
                  setStep('review')
                }}
              >
                Try again
              </Button>
            )}
            <Button variant="primary" onClick={onClose}>
              Close
            </Button>
          </>
        )}
      </ModalFooter>
    </Modal>
  )
}
