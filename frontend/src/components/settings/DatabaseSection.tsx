import { useState } from 'react'
import {
  useDbStatus,
  useMigrateDb,
  useSetDbUrl,
  useSetupDockerDb,
  useTeardownDockerDb,
} from '../../hooks/useDb'
import { Button, Skeleton, ErrorState } from '../ui'
import { errorMessage } from '../../lib/errors'

const inputCls =
  'border border-border rounded-md px-3 py-1.5 text-sm bg-canvas focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent w-full font-mono'

function SchemaBadge({
  migration,
}: {
  migration: {
    up_to_date: boolean
    error: string | null
    current_revision: string | null
  }
}) {
  if (migration.error)
    return (
      <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-danger-subtle text-danger border border-danger-muted">
        unreachable
      </span>
    )
  if (migration.up_to_date)
    return (
      <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-success-subtle text-success border border-success-muted">
        up to date
      </span>
    )
  return (
    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-attention-subtle text-attention border border-attention-muted">
      pending migrations
    </span>
  )
}

export default function DatabaseSection() {
  const { data: status, isLoading, error } = useDbStatus()
  const migrate = useMigrateDb()
  const setUrl = useSetDbUrl()
  const setupDocker = useSetupDockerDb()
  const teardownDocker = useTeardownDockerDb()

  const [editingUrl, setEditingUrl] = useState(false)
  const [urlInput, setUrlInput] = useState('')
  const [confirmTeardown, setConfirmTeardown] = useState(false)

  if (isLoading)
    return (
      <div className="space-y-6" aria-hidden="true">
        <div className="space-y-2">
          <Skeleton className="h-5 w-24" />
          <Skeleton className="h-4 w-80" />
        </div>
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-28 w-full" />
      </div>
    )
  if (error || !status)
    return (
      <ErrorState
        message={error ? errorMessage(error) : 'Failed to load database status'}
      />
    )

  const dockerState = status.docker
    ? status.docker.running
      ? 'running'
      : status.docker.exists
        ? 'stopped'
        : status.docker.volume_exists
          ? 'missing (data volume present)'
          : 'missing (data volume gone)'
    : null

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-fg">Database</h2>
        <p className="text-sm text-fg-muted mt-0.5">
          Connection, schema, and provisioning for this project's database.
        </p>
      </div>

      <div className="border border-border rounded-md bg-canvas p-4 space-y-3">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-xs font-mono text-fg truncate">{status.url}</p>
            <p className="text-xs text-fg-muted mt-0.5">
              {status.dialect} — managed by{' '}
              {status.docker_managed ? 'civex (Docker)' : 'you'}
            </p>
          </div>
          <SchemaBadge migration={status.migration} />
        </div>

        {status.migration.error && (
          <p className="text-xs text-danger bg-danger-subtle border border-danger-muted rounded px-3 py-2">
            {status.migration.error}
          </p>
        )}

        {!status.migration.up_to_date && !status.migration.error && (
          <p className="text-xs text-fg-muted">
            At {status.migration.current_revision ?? 'no revision yet'}, head is{' '}
            {status.migration.head_revision}.
          </p>
        )}

        <div className="flex items-center gap-2">
          <Button
            size="sm"
            onClick={() => migrate.mutate()}
            disabled={migrate.isPending || status.migration.up_to_date}
          >
            {migrate.isPending ? 'Migrating…' : 'Run migrations'}
          </Button>
          {migrate.error && (
            <span className="text-xs text-danger">
              {errorMessage(migrate.error)}
            </span>
          )}
        </div>
      </div>

      {/* Change URL */}
      <div className="border border-border rounded-md bg-canvas p-4 space-y-3">
        <p className="text-sm font-semibold text-fg">
          Point at a different database
        </p>
        <p className="text-xs text-fg-muted">
          Tests the connection, then migrates it to the current schema. The
          database itself is not modified — only which one civex uses.
        </p>
        {!editingUrl ? (
          <Button size="sm" onClick={() => setEditingUrl(true)}>
            Change URL…
          </Button>
        ) : (
          <div className="space-y-2">
            <input
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              placeholder="postgresql+psycopg2://user:pass@host:5432/dbname"
              className={inputCls}
              autoFocus
            />
            {setUrl.error && (
              <p className="text-xs text-danger">
                {errorMessage(setUrl.error)}
              </p>
            )}
            <div className="flex gap-2">
              <Button
                variant="primary"
                size="sm"
                disabled={!urlInput.trim() || setUrl.isPending}
                onClick={() =>
                  setUrl.mutate(urlInput.trim(), {
                    onSuccess: () => {
                      setEditingUrl(false)
                      setUrlInput('')
                    },
                  })
                }
              >
                {setUrl.isPending ? 'Testing…' : 'Test & save'}
              </Button>
              <Button
                size="sm"
                onClick={() => {
                  setEditingUrl(false)
                  setUrlInput('')
                }}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Docker management */}
      <div className="border border-border rounded-md bg-canvas p-4 space-y-3">
        <p className="text-sm font-semibold text-fg">
          Docker-managed PostgreSQL
        </p>
        {status.docker_managed ? (
          <>
            <p className="text-xs text-fg-muted">
              Container <span className="font-mono">{status.docker?.name}</span>{' '}
              — {dockerState}
            </p>
            {setupDocker.error && (
              <p className="text-xs text-danger">
                {errorMessage(setupDocker.error)}
              </p>
            )}
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={() => setupDocker.mutate()}
                disabled={setupDocker.isPending}
              >
                {setupDocker.isPending
                  ? 'Starting…'
                  : 'Start / recreate container'}
              </Button>
              {!confirmTeardown ? (
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => setConfirmTeardown(true)}
                >
                  Tear down…
                </Button>
              ) : (
                <>
                  <Button
                    variant="danger"
                    size="sm"
                    disabled={teardownDocker.isPending}
                    onClick={() =>
                      teardownDocker.mutate(undefined, {
                        onSuccess: () => setConfirmTeardown(false),
                      })
                    }
                  >
                    {teardownDocker.isPending
                      ? 'Removing…'
                      : 'Confirm: delete container + data'}
                  </Button>
                  <Button size="sm" onClick={() => setConfirmTeardown(false)}>
                    Cancel
                  </Button>
                </>
              )}
            </div>
            {teardownDocker.error && (
              <p className="text-xs text-danger">
                {errorMessage(teardownDocker.error)}
              </p>
            )}
          </>
        ) : (
          <>
            <p className="text-xs text-fg-muted">
              Starts (or reuses) a local postgres:16 container for this project,
              then migrates it and switches civex to use it.
            </p>
            {setupDocker.error && (
              <p className="text-xs text-danger">
                {errorMessage(setupDocker.error)}
              </p>
            )}
            <Button
              size="sm"
              onClick={() => setupDocker.mutate()}
              disabled={setupDocker.isPending}
            >
              {setupDocker.isPending ? 'Setting up…' : 'Set up Docker Postgres'}
            </Button>
          </>
        )}
      </div>
    </div>
  )
}
