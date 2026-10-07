import { Link } from 'react-router'
import { type WorkflowJob } from '../../api/workflows'
import { Badge, Subheading } from '../ui'
import {
  LONG_CHAIN,
  causedBy,
  describeTrigger,
  runProblems,
  summarizeRun,
} from '../../utils/runNarrative'

/** Which fields changed to start this run, from what to what, and whether the
 * workflow was watching each one. */
function WhatChanged({ job }: { job: WorkflowJob }) {
  const changes = job.trigger_detail?.changes ?? []
  if (job.trigger !== 'record_updated') return null
  if (!job.trigger_detail)
    return (
      <p className="text-xs text-fg-muted">
        Which field changed wasn&apos;t recorded for this run.
      </p>
    )
  if (changes.length === 0) return null
  return (
    <div>
      <Subheading as="h3">What changed</Subheading>
      <ul className="mt-1 space-y-1 text-sm">
        {changes.map((c) => (
          <li
            key={c.field}
            className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5"
          >
            <span className="font-mono text-fg">{c.field}</span>
            <span className="text-fg-muted">
              {c.before ?? 'empty'} → {c.after ?? 'empty'}
            </span>
            <Badge variant={c.watched ? 'accent' : 'default'}>
              {c.watched ? 'what started it' : 'also changed'}
            </Badge>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** The run behind this one, when another run's own save started it, and a
 * warning once such a chain has grown long. */
function WhatCausedIt({ job }: { job: WorkflowJob }) {
  const cause = causedBy(job)
  if (!cause) return null
  return (
    <div className="space-y-1 text-sm">
      <p className="text-fg">
        Started by{' '}
        <Link
          to={`/runs/${cause.job_id}`}
          className="text-accent hover:underline"
        >
          a run of {cause.workflow ?? 'another workflow'}
        </Link>
        , which saved this record. This is step {job.depth} in a chain of runs.
      </p>
      {job.depth >= LONG_CHAIN && (
        <p role="note" className="text-attention">
          Runs are triggering each other. Use <strong>Stop automation</strong>{' '}
          on the Runs page to end it.
        </p>
      )}
    </div>
  )
}

/** What a run that finished still got wrong, up front and in the warning colour,
 * with the files it names, so a green-looking run can't hide it. */
function Problems({ job }: { job: WorkflowJob }) {
  if (job.status !== 'completed') return null
  const { lines, items } = runProblems(job)
  if (lines.length === 0) return null
  return (
    <div
      role="alert"
      className="space-y-1 rounded-md border border-attention-muted bg-attention-subtle px-3 py-2 text-sm text-attention"
    >
      <p className="font-medium">
        This run finished, but not everything worked:
      </p>
      <ul className="list-disc pl-5">
        {lines.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
      {items.length > 0 && (
        <ul className="max-h-40 space-y-0.5 overflow-y-auto font-mono text-xs">
          {items.map((i, n) => (
            <li key={n}>{i.text}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function RunSummary({ job }: { job: WorkflowJob }) {
  const isActive = job.status === 'pending' || job.status === 'running'
  const summary = summarizeRun(job)

  return (
    <div className="space-y-3">
      <p className="text-sm text-fg">{describeTrigger(job)}</p>
      <Problems job={job} />
      <WhatChanged job={job} />
      <WhatCausedIt job={job} />

      {isActive ? (
        <p className="text-sm text-fg-muted">Running…</p>
      ) : summary.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {summary.map((phrase) => (
            <Badge key={phrase} variant="default">
              {phrase}
            </Badge>
          ))}
        </div>
      ) : (
        <p className="text-sm text-fg-muted">
          {job.status === 'completed'
            ? "This run didn't create or change any records."
            : job.status === 'cancelled'
              ? 'No records were created or changed before this run was stopped.'
              : 'No records were created or changed before this run failed.'}
        </p>
      )}
    </div>
  )
}
