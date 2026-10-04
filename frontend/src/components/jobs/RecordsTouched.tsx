import { Link } from 'react-router'
import type { WorkflowJob } from '../../api/workflows'
import { Badge } from '../ui'
import { RecordName } from '../records/RecordName'

/** The records a run created or changed, each named as it is now (see
 * `RecordName`), in the order the run touched them. */
export default function RecordsTouched({ job }: { job: WorkflowJob }) {
  const records = job.affected_records ?? []
  const active = job.status === 'pending' || job.status === 'running'

  if (records.length === 0)
    return (
      <p className="text-sm text-fg-muted">
        {active
          ? 'Running…'
          : job.status === 'completed'
            ? "This run didn't create or change any records."
            : job.status === 'cancelled'
              ? 'No records were created or changed before this run was stopped.'
              : 'No records were created or changed before this run failed.'}
      </p>
    )

  return (
    <ul className="divide-y divide-border-muted rounded-md border border-border">
      {records.map((rec) => (
        <li
          key={rec.record_id}
          className="flex items-center gap-3 px-4 py-2 text-sm"
        >
          <Badge
            variant={rec.action === 'created' ? 'success' : 'accent'}
            className="shrink-0"
          >
            {rec.action}
          </Badge>
          <Link
            to={`/records/${rec.record_id}`}
            className="min-w-0 truncate text-accent hover:underline"
          >
            <RecordName
              id={rec.record_id}
              fallback={rec.natural_name ?? null}
            />
          </Link>
          <span className="text-xs text-fg-muted">{rec.schema_name}</span>
        </li>
      ))}
    </ul>
  )
}
