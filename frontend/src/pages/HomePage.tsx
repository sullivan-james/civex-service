import { Link } from 'react-router'
import { useJobsPaged } from '../hooks/useWorkflows'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Page,
  StepBadge,
} from '../components/ui'
import { ArrowRight } from '../components/ui/icons'
import { HomeShortcuts } from '../components/home/HomeShortcuts'

const ONBOARDING_STEPS = [
  { to: '/collections', title: 'Import data' },
  { to: '/schemas', title: 'Create a record type' },
  { to: '/runs', title: 'Automate the rest' },
]

function jobBadgeVariant(status: string): 'success' | 'danger' | 'default' {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  return 'default'
}

export default function HomePage() {
  const { jobs } = useJobsPaged(0, 5)
  const recentJobs = jobs.data ?? []

  return (
    <Page title="Get started">
      <HomeShortcuts />

      <ol className="grid gap-3 sm:grid-cols-3">
        {ONBOARDING_STEPS.map((s, i) => (
          <li key={s.to}>
            <Card
              to={s.to}
              title={
                <span className="flex items-center gap-3">
                  <StepBadge index={i + 1} state="current" />
                  {s.title}
                </span>
              }
              action={
                <ArrowRight
                  size={16}
                  className="text-fg-subtle"
                  aria-hidden="true"
                />
              }
            />
          </li>
        ))}
      </ol>

      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-fg">Recent activity</h2>
          <Button size="sm" variant="link" to="/runs">
            View all runs
          </Button>
        </div>
        {recentJobs.length === 0 ? (
          <EmptyState title="Nothing has run yet" />
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
