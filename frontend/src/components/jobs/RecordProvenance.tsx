import { Link } from 'react-router'
import { useJobsAffectingRecord } from '../../hooks/useWorkflows'
import { Badge, Card } from '../ui'

// The reverse of JobsTable's recordId filter: not "runs this record
// triggered" but "runs that created or changed this record" -- so a
// scientist looking at a record that showed up unexpectedly can trace it
// back to the automation that produced it.
export default function RecordProvenance({ recordId }: { recordId: string }) {
  const { data: jobs } = useJobsAffectingRecord(recordId)
  if (!jobs || jobs.length === 0) return null

  return (
    <Card title="Runs that changed this record" count={jobs.length}>
      <ul className="space-y-1.5">
        {jobs.map((job) => {
          const touch = job.affected_records?.find(
            (r) => r.record_id === recordId,
          )
          return (
            <li key={job.id} className="flex items-center gap-2 text-sm">
              {touch && (
                <Badge
                  variant={touch.action === 'created' ? 'success' : 'accent'}
                >
                  {touch.action}
                </Badge>
              )}
              <Link
                to={`/runs/${job.id}`}
                className="text-accent hover:underline"
              >
                {job.workflow_name}
              </Link>
              <span className="text-fg-muted text-xs">
                {new Date(job.created_at).toLocaleString()}
              </span>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}
