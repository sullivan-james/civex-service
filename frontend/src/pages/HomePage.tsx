import { type ComponentType } from 'react'
import { Link } from 'react-router'
import { useJobsPaged } from '../hooks/useWorkflows'
import { Badge, Page } from '../components/ui'
import {
  ArrowRight,
  Database,
  ListChecks,
  Upload,
} from '../components/ui/icons'

interface StartTileProps {
  to: string
  icon: ComponentType<{
    size?: number
    className?: string
    'aria-hidden'?: boolean | 'true'
  }>
  title: string
  description: string
}

function StartTile({ to, icon: Icon, title, description }: StartTileProps) {
  return (
    <Link
      to={to}
      className="group flex flex-col gap-3 rounded-lg border border-border bg-canvas p-4 transition-colors hover:border-accent-subtle-border hover:bg-canvas-subtle"
    >
      <div className="flex items-center justify-between">
        <span className="inline-flex h-9 w-9 items-center justify-center rounded-md bg-accent-subtle text-accent">
          <Icon size={18} aria-hidden="true" />
        </span>
        <ArrowRight
          size={16}
          className="text-fg-subtle transition-colors group-hover:text-accent"
          aria-hidden="true"
        />
      </div>
      <div>
        <h2 className="text-sm font-semibold text-fg">{title}</h2>
        <p className="mt-0.5 text-sm text-fg-muted">{description}</p>
      </div>
    </Link>
  )
}

function jobBadgeVariant(status: string): 'success' | 'danger' | 'default' {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  return 'default'
}

export default function HomePage() {
  const { jobs } = useJobsPaged(0, 5)
  const recentJobs = jobs.data ?? []

  return (
    <Page
      title="Get started"
      description="Import data, define record types, and let automations handle the rest."
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <StartTile
          to="/collections"
          icon={Upload}
          title="Import data"
          description="Bring in files or a spreadsheet and turn them into records."
        />
        <StartTile
          to="/schemas"
          icon={Database}
          title="Create a record type"
          description="Define the fields your records will have before you start adding data."
        />
        <StartTile
          to="/runs"
          icon={ListChecks}
          title="View recent activity"
          description="See what automations have run and whether they succeeded."
        />
      </div>

      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-fg">Recent activity</h2>
          <Link to="/runs" className="text-xs text-accent hover:underline">
            View all runs
          </Link>
        </div>
        {recentJobs.length === 0 ? (
          <div className="rounded-md border border-dashed border-border px-6 py-8 text-center text-sm text-fg-muted">
            Nothing has run yet. Runs appear here once an automation is
            triggered.
          </div>
        ) : (
          <ul className="divide-y divide-border-muted rounded-md border border-border">
            {recentJobs.map((job) => (
              <li
                key={job.id}
                className="flex items-center justify-between gap-4 px-4 py-2.5 text-sm"
              >
                <div className="min-w-0">
                  <Link
                    to={`/runs/${job.id}`}
                    className="font-medium text-accent hover:underline"
                  >
                    {job.workflow_name}
                  </Link>
                  <span className="ml-2 text-xs text-fg-subtle">
                    {new Date(job.created_at).toLocaleString()}
                  </span>
                </div>
                <Badge variant={jobBadgeVariant(job.status)}>
                  {job.status}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Page>
  )
}
