import { useState } from 'react'
import { Button } from '../../ui'
import { useDbStatus, useDbSummary, useMigrateDb } from '../../../hooks/useDb'
import { errorMessage } from '../../../lib/errors'
import { formatSize } from '../../../utils/dbFormat'
import { MoveDatabaseWizard } from './MoveDatabaseWizard'

/** The database this project uses now: what it is, where, how big, whether
 * it's healthy -- and the one way to change it. */
export function CurrentDatabaseCard() {
  const { data: summary } = useDbSummary()
  const { data: status } = useDbStatus()
  const migrate = useMigrateDb()
  const [moving, setMoving] = useState(false)

  if (!summary || !status) return null
  const migration = status.migration

  return (
    <div className="border border-border rounded-md bg-canvas p-4 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-semibold text-fg">
            <span
              aria-hidden="true"
              className={`inline-block h-2 w-2 rounded-full ${
                summary.reachable && !migration.error
                  ? 'bg-success'
                  : 'bg-danger'
              }`}
            />
            {summary.label}
          </p>
          <p
            className="text-xs font-mono text-fg-muted truncate mt-1"
            title={summary.location}
          >
            {summary.location}
          </p>
          {summary.reachable && (
            <p className="text-xs text-fg-muted mt-1">
              {summary.records.toLocaleString()} records ·{' '}
              {formatSize(summary.size_bytes)}
            </p>
          )}
        </div>
        <Button onClick={() => setMoving(true)}>
          Move to another database…
        </Button>
      </div>

      {(!summary.reachable || migration.error) && (
        <p
          role="alert"
          className="text-xs text-danger bg-danger-subtle border border-danger-muted rounded-md px-3 py-2"
        >
          Can&rsquo;t reach this database: {migration.error ?? summary.error}
        </p>
      )}

      {summary.reachable && !migration.error && migration.up_to_date && (
        <p className="text-xs text-fg-muted">Connected · schema up to date</p>
      )}

      {summary.reachable && !migration.error && !migration.up_to_date && (
        <div className="flex flex-wrap items-center gap-3 text-xs bg-attention-subtle border border-attention-muted rounded-md px-3 py-2">
          <span className="text-attention">
            This database&rsquo;s structure is out of date.
          </span>
          <Button
            size="sm"
            onClick={() => migrate.mutate()}
            disabled={migrate.isPending}
          >
            {migrate.isPending ? 'Updating…' : 'Update it'}
          </Button>
          {migrate.error && (
            <span className="text-danger">{errorMessage(migrate.error)}</span>
          )}
        </div>
      )}

      {moving && <MoveDatabaseWizard onClose={() => setMoving(false)} />}
    </div>
  )
}
