import { Link } from 'react-router'
import { useJobsPaged } from '../hooks/useWorkflows'
import { useCollections } from '../hooks/useCollections'
import { useFeatures } from '../hooks/useFeatures'
import { offered } from '../utils/features'
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
import { DesktopShortcut } from '../components/settings/DesktopShortcut'
import { formatTimestamp } from '../utils/dates'

const ONBOARDING_STEPS = [
  { to: '/collections', title: 'Start a collection' },
  { to: '/collections', title: 'Add records' },
  { to: '/runs', title: 'Automate the rest', feature: 'local_workflows' },
]

function jobBadgeVariant(status: string): 'success' | 'danger' | 'default' {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  return 'default'
}

function RecentActivity() {
  const { jobs } = useJobsPaged(0, 5)
  const recentJobs = jobs.data ?? []

  return (
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
                  {formatTimestamp(job.created_at)}
                </span>
              </div>
              <Badge variant={jobBadgeVariant(job.status)}>{job.status}</Badge>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function HomePage() {
  const features = useFeatures()
  const dials = offered(features, { feature: 'remote_dial' })
  const { data: collections, isPending, isSuccess } = useCollections()
  // Steps are for an empty project: once there is a collection, the shortcuts
  // above are the way back in. Steps that need a feature the server lacks
  // (workflows, say) are not offered.
  const steps = ONBOARDING_STEPS.filter((s) => offered(features, s))
  const started = (collections?.length ?? 0) > 0

  return (
    <Page title={isPending ? undefined : started ? 'Home' : 'Get started'}>
      <HomeShortcuts />
      <DesktopShortcut prompt />

      {started && (
        <ul className="divide-y divide-border-muted rounded-md border border-border">
          {(collections ?? []).map((c) => (
            <li key={c.id}>
              <Link
                to={`/collections/${c.id}`}
                className="flex items-center justify-between gap-4 px-4 py-2.5 text-sm hover:bg-canvas-subtle"
              >
                <span className="font-medium text-accent">{c.name}</span>
                <span className="text-xs text-fg-subtle">
                  {c.record_count.toLocaleString()} records
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {isSuccess && !started && (
        <ol
          className={`grid gap-3 ${steps.length === 3 ? 'sm:grid-cols-3' : 'sm:grid-cols-2'}`}
        >
          {steps.map((s, i) => (
            <li key={s.title}>
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
      )}

      {isSuccess && !started && (
        <p className="mt-4 text-sm text-fg-muted">
          Have a spreadsheet?{' '}
          <Link to="/import" className="text-accent hover:underline">
            Import it
          </Link>
          .
          {dials && (
            <>
              {' '}
              Or{' '}
              <Link to="/connect" className="text-accent hover:underline">
                connect to a hub
              </Link>
              .
            </>
          )}
        </p>
      )}

      {offered(features, { feature: 'local_workflows' }) && <RecentActivity />}
    </Page>
  )
}
