import { Link } from 'react-router'
import { type WorkflowJob } from '../../api/workflows'
import { Badge } from '../ui'
import { describeTrigger, summarizeRun } from '../../utils/runNarrative'

function ActionBadge({ action }: { action: 'created' | 'updated' }) {
  return (
    <Badge
      variant={action === 'created' ? 'success' : 'accent'}
      className="shrink-0"
    >
      {action}
    </Badge>
  )
}

export default function RunSummary({ job }: { job: WorkflowJob }) {
  const isActive = job.status === 'pending' || job.status === 'running'
  const summary = summarizeRun(job)
  const records = job.affected_records ?? []

  return (
    <div className="space-y-3">
      <p className="text-sm text-fg">{describeTrigger(job)}</p>

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
            : 'No records were created or changed before this run failed.'}
        </p>
      )}

      {records.length > 0 && (
        <div>
          <h3 className="text-xs font-medium text-fg-muted uppercase tracking-wide mb-1">
            Records touched
          </h3>
          <ul className="space-y-1">
            {records.map((rec) => (
              <li
                key={rec.record_id}
                className="flex items-center gap-2 text-sm"
              >
                <ActionBadge action={rec.action} />
                <Link
                  to={`/records/${rec.record_id}`}
                  className="text-accent hover:underline"
                >
                  {rec.natural_name ?? rec.record_id.slice(0, 8) + '…'}
                </Link>
                <span className="text-fg-muted text-xs">{rec.schema_name}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
