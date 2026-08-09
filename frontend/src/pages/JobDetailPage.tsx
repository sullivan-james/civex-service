import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useJob, useRerunJob } from '../hooks/useWorkflows'
import { usePlugins } from '../hooks/usePlugins'
import { type WorkflowJob } from '../api/workflows'
import {
  Badge,
  Button,
  DetailSkeleton,
  ErrorState,
  Page,
} from '../components/ui'
import StepExecutionCard from '../components/jobs/StepExecutionCard'
import JobStepsDiagram from '../components/jobs/JobStepsDiagram'
import JobStatusBadge from '../components/jobs/JobStatusBadge'
import RunSummary from '../components/jobs/RunSummary'
import FailureExplanation from '../components/jobs/FailureExplanation'
import { RefreshCw } from '../components/ui/icons'

function duration(job: WorkflowJob): string | null {
  if (!job.started_at) return null
  const end = job.finished_at ? new Date(job.finished_at) : new Date()
  const secs = (end.getTime() - new Date(job.started_at).getTime()) / 1000
  return secs < 60 ? `${secs.toFixed(2)}s` : `${(secs / 60).toFixed(2)}m`
}

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: job, isLoading, error } = useJob(id ?? '')
  const { data: plugins } = usePlugins()
  const rerun = useRerunJob()
  const [view, setView] = useState<'list' | 'diagram'>('list')

  const breadcrumbs = [{ label: 'Runs', to: '/runs' }]

  if (isLoading)
    return (
      <Page
        breadcrumbs={breadcrumbs}
        loading={<DetailSkeleton metadataRows={6} sections={1} />}
      />
    )
  if (error)
    return (
      <Page
        breadcrumbs={breadcrumbs}
        error={<ErrorState message={error.message} />}
      />
    )
  if (!job)
    return (
      <Page
        breadcrumbs={breadcrumbs}
        error={<ErrorState message="Run not found" />}
      />
    )

  const isActive = job.status === 'pending' || job.status === 'running'

  return (
    <Page
      breadcrumbs={[
        { label: 'Runs', to: '/runs' },
        { label: `${job.id.slice(0, 8)}…` },
      ]}
      title={job.workflow_name}
      description={<span className="font-mono">{job.id}</span>}
      action={
        <div className="flex items-center gap-2">
          {isActive && (
            <span className="text-xs text-accent animate-pulse">live</span>
          )}
          <JobStatusBadge status={job.status} />
          <Button
            size="sm"
            disabled={rerun.isPending}
            onClick={() =>
              rerun
                .mutateAsync(job.id)
                .then((newJob) => navigate(`/runs/${newJob.id}`))
            }
          >
            <RefreshCw size={12} />
            {rerun.isPending ? 'Re-running…' : 'Re-run'}
          </Button>
        </div>
      }
    >
      {/* What this run did, in plain language */}
      <div className="border border-border rounded-md p-4 bg-canvas-subtle">
        <RunSummary job={job} />
      </div>

      {/* Failure, explained */}
      {job.status === 'failed' && <FailureExplanation job={job} />}

      {/* Metadata grid -- the technical particulars */}
      <dl className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm border border-border rounded-md p-4">
        <div>
          <dt className="text-fg-muted font-medium">Record</dt>
          <dd>
            <Link
              to={`/records/${job.record_id}`}
              className="font-mono text-accent hover:underline text-xs"
            >
              {job.record_id.slice(0, 8)}…
            </Link>
          </dd>
        </div>
        <div>
          <dt className="text-fg-muted font-medium">Schema</dt>
          <dd className="text-fg">{job.schema_name}</dd>
        </div>
        <div>
          <dt className="text-fg-muted font-medium">Trigger</dt>
          <dd>
            <Badge variant="default">{job.trigger}</Badge>
          </dd>
        </div>
        <div>
          <dt className="text-fg-muted font-medium">Duration</dt>
          <dd className="text-fg">{duration(job) ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-fg-muted font-medium">Created</dt>
          <dd className="text-fg">
            {new Date(job.created_at).toLocaleString()}
          </dd>
        </div>
        {job.finished_at && (
          <div>
            <dt className="text-fg-muted font-medium">Finished</dt>
            <dd className="text-fg">
              {new Date(job.finished_at).toLocaleString()}
            </dd>
          </div>
        )}
      </dl>

      {/* Steps -- the advanced/technical view; collapsed narrative by
          default, full inputs/outputs one click away (StepExecutionCard). */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-fg">
            Steps
            {isActive && (
              <span className="ml-2 text-xs font-normal text-accent animate-pulse">
                updating…
              </span>
            )}
          </h2>
          {job.step_executions && job.step_executions.length > 0 && (
            <div className="flex gap-1">
              <Button
                size="sm"
                variant={view === 'list' ? 'primary' : 'default'}
                onClick={() => setView('list')}
              >
                List
              </Button>
              <Button
                size="sm"
                variant={view === 'diagram' ? 'primary' : 'default'}
                onClick={() => setView('diagram')}
              >
                Diagram
              </Button>
            </div>
          )}
        </div>
        {job.step_executions && job.step_executions.length > 0 ? (
          view === 'diagram' ? (
            <JobStepsDiagram steps={job.step_executions} plugins={plugins} />
          ) : (
            <div className="space-y-2">
              {job.step_executions.map((step) => (
                <StepExecutionCard
                  key={step.step_id}
                  step={step}
                  plugins={plugins}
                />
              ))}
            </div>
          )
        ) : job.log ? (
          // Jobs that predate per-step execution records (CIVEX-117/118)
          // only have the flat captured-output blob to fall back to.
          <pre className="text-xs font-mono bg-nav-surface-strong text-nav-fg-muted rounded-md p-4 overflow-auto max-h-[60vh] whitespace-pre-wrap leading-relaxed">
            {job.log}
          </pre>
        ) : (
          <div className="border border-dashed border-border rounded-md p-6 text-sm text-center text-fg-muted">
            {isActive ? 'Waiting for output…' : 'No output captured.'}
          </div>
        )}
      </div>
    </Page>
  )
}
