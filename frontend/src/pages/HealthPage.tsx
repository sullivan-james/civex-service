import { Badge, Button, Page } from '../components/ui'
import { useHealth, useRepair } from '../hooks/useHealth'
import { errorMessage } from '../lib/errors'

/** What `civex doctor` checks, with the same repair. */
export default function HealthPage() {
  const health = useHealth()
  const repair = useRepair()
  const data = health.data

  return (
    <Page
      title="Health"
      info="Checks this project's database, its references and records, and where its files are kept. Repair adds any table or column the database lacks, after saving a backup of it."
      loading={health.isLoading ? 'Checking…' : undefined}
      error={health.error ? errorMessage(health.error) : undefined}
      action={
        <div className="flex gap-2">
          <Button onClick={() => health.refetch()} disabled={health.isFetching}>
            {health.isFetching ? 'Checking…' : 'Check'}
          </Button>
          {data?.can_repair && (
            <Button
              variant="primary"
              onClick={() => repair.mutate()}
              disabled={repair.isPending}
            >
              {repair.isPending ? 'Repairing…' : 'Repair'}
            </Button>
          )}
        </div>
      }
    >
      {data && (
        <div className="space-y-4">
          {data.ok && <p className="text-fg">No problems found.</p>}
          {!data.data_checked && (
            <p className="text-fg-muted">
              The records were not checked: the database lacks something.
            </p>
          )}
          <ul className="space-y-3">
            {data.problems.map((p, i) => (
              <li key={i} className="rounded border border-border p-3">
                <div className="flex items-start gap-2">
                  <Badge
                    variant={p.severity === 'fail' ? 'danger' : 'attention'}
                  >
                    {p.severity === 'fail' ? 'Problem' : 'Note'}
                  </Badge>
                  <span className="text-fg">{p.message}</span>
                </div>
                {p.kind === 'database' && p.items.length > 0 && (
                  <p className="mt-1 text-sm text-fg-muted">
                    Missing: {p.items.join(', ')}
                  </p>
                )}
                {p.kind !== 'database' && p.items.length > 0 && (
                  <ul className="mt-1 text-sm text-fg-muted">
                    {p.items.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                )}
                {p.fix && <p className="mt-1 text-sm text-fg-muted">{p.fix}</p>}
              </li>
            ))}
          </ul>
          {data.checks && (
            <ul className="space-y-1 text-sm text-fg-muted">
              {data.checks.map((c) => (
                <li key={c.name}>
                  {c.name}: {c.detail}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Page>
  )
}
