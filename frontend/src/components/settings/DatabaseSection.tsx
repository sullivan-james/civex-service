import { useState } from 'react'
import {
  useDbStatus,
  useMigrateDb,
  useSetDbUrl,
  useSetupDockerDb,
  useTeardownDockerDb,
} from '../../hooks/useDb'
import { Button, LoadingState, ErrorState } from '../ui'
import { errorMessage } from '../../lib/errors'

const inputCls =
  'border border-[#d0d7de] rounded-md px-3 py-2 text-sm bg-white focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da] w-full font-mono'

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
      <span className="text-xs font-medium px-2 py-1 rounded-full bg-[#ffebe9] text-[#d1242f] border border-[#ff818255]">
        unreachable
      </span>
    )
  if (migration.up_to_date)
    return (
      <span className="text-xs font-medium px-2 py-1 rounded-full bg-[#dafbe1] text-[#1a7f37] border border-[#4ac26b55]">
        up to date
      </span>
    )
  return (
    <span className="text-xs font-medium px-2 py-1 rounded-full bg-[#fff8c5] text-[#9a6700] border border-[#d4a72c55]">
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

  if (isLoading) return <LoadingState />
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
        <h2 className="text-lg font-semibold text-[#1f2328]">Database</h2>
        <p className="text-sm text-[#656d76] mt-1">
          Connection, schema, and provisioning for this project's database.
        </p>
      </div>

      <div className="border border-[#d0d7de] rounded-md bg-white p-4 space-y-3">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-xs font-mono text-[#1f2328] truncate">
              {status.url}
            </p>
            <p className="text-xs text-[#656d76] mt-1">
              {status.dialect} — managed by{' '}
              {status.docker_managed ? 'civex (Docker)' : 'you'}
            </p>
          </div>
          <SchemaBadge migration={status.migration} />
        </div>

        {status.migration.error && (
          <p className="text-xs text-[#d1242f] bg-[#ffebe9] border border-[#d1242f33] rounded-md px-3 py-2">
            {status.migration.error}
          </p>
        )}

        {!status.migration.up_to_date && !status.migration.error && (
          <p className="text-xs text-[#656d76]">
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
            <span className="text-xs text-[#d1242f]">
              {errorMessage(migrate.error)}
            </span>
          )}
        </div>
      </div>

      {/* Change URL */}
      <div className="border border-[#d0d7de] rounded-md bg-white p-4 space-y-3">
        <p className="text-sm font-semibold text-[#1f2328]">
          Point at a different database
        </p>
        <p className="text-xs text-[#656d76]">
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
              <p className="text-xs text-[#d1242f]">
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
      <div className="border border-[#d0d7de] rounded-md bg-white p-4 space-y-3">
        <p className="text-sm font-semibold text-[#1f2328]">
          Docker-managed PostgreSQL
        </p>
        {status.docker_managed ? (
          <>
            <p className="text-xs text-[#656d76]">
              Container <span className="font-mono">{status.docker?.name}</span>{' '}
              — {dockerState}
            </p>
            {setupDocker.error && (
              <p className="text-xs text-[#d1242f]">
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
              <p className="text-xs text-[#d1242f]">
                {errorMessage(teardownDocker.error)}
              </p>
            )}
          </>
        ) : (
          <>
            <p className="text-xs text-[#656d76]">
              Starts (or reuses) a local postgres:16 container for this project,
              then migrates it and switches civex to use it.
            </p>
            {setupDocker.error && (
              <p className="text-xs text-[#d1242f]">
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
