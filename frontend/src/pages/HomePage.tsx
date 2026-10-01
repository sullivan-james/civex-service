import { Link } from 'react-router'
import { useJobsPaged } from '../hooks/useWorkflows'
import { Badge, EmptyState, Page, StepBadge } from '../components/ui'
import { ArrowRight } from '../components/ui/icons'
import { HomeShortcuts } from '../components/home/HomeShortcuts'

interface OnboardingStep {
  to: string
  title: string
  description: string
}

const ONBOARDING_STEPS: OnboardingStep[] = [
  {
    to: '/collections',
    title: 'Import data',
    description: 'Bring in files or a spreadsheet and turn them into records.',
  },
  {
    to: '/schemas',
    title: 'Create a record type',
    description:
      'Define the fields your records will have before you start adding data.',
  },
  {
    to: '/runs',
    title: 'Automate the rest',
    description: 'See what automations have run and whether they succeeded.',
  },
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
    <Page
      title="Get started"
      description="Import data, define record types, and let automations handle the rest."
    >
      <HomeShortcuts />

      <ol className="flex flex-col gap-3 sm:flex-row sm:gap-0">
        {ONBOARDING_STEPS.map((s, i) => (
          <li key={s.to} className="flex sm:flex-1">
            <Link
              to={s.to}
              className="group flex flex-1 items-start gap-3 rounded-lg border border-border bg-canvas p-4 transition-colors hover:border-accent-subtle-border hover:bg-canvas-subtle"
            >
              <StepBadge index={i + 1} state="current" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <h2 className="text-sm font-semibold text-fg">{s.title}</h2>
                  <ArrowRight
                    size={16}
                    className="shrink-0 text-fg-subtle transition-colors group-hover:text-accent"
                    aria-hidden="true"
                  />
                </div>
                <p className="mt-0.5 text-sm text-fg-muted">{s.description}</p>
              </div>
            </Link>
            {i < ONBOARDING_STEPS.length - 1 && (
              <div
                className="hidden shrink-0 items-center px-2 sm:flex"
                aria-hidden="true"
              >
                <div className="h-px w-4 bg-border" />
              </div>
            )}
          </li>
        ))}
      </ol>

      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-fg">Recent activity</h2>
          <Link to="/runs" className="text-xs text-accent hover:underline">
            View all runs
          </Link>
        </div>
        {recentJobs.length === 0 ? (
          <EmptyState
            title="Nothing has run yet"
            message="Runs appear here once an automation is triggered."
          />
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
