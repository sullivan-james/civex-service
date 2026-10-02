import { useState } from 'react'
import {
  Button,
  CollapsibleSection,
  ConfirmDialog,
  Field,
  Input,
} from '../../ui'
import {
  useDbStatus,
  useMigrateDb,
  useSetDbUrl,
  useSetupDockerDb,
  useTeardownDockerDb,
} from '../../../hooks/useDb'
import { errorMessage } from '../../../lib/errors'

/** The rarely-needed controls, kept out of the way: the raw connection, the
 * Docker container's lifecycle, and pointing at a database without moving
 * data. None of these copy anything. */
export function AdvancedDatabase() {
  const { data: status } = useDbStatus()
  const migrate = useMigrateDb()
  const setUrl = useSetDbUrl()
  const setupDocker = useSetupDockerDb()
  const teardown = useTeardownDockerDb()
  const [urlInput, setUrlInput] = useState('')
  const [confirmTeardown, setConfirmTeardown] = useState(false)

  if (!status) return null
  const docker = status.docker
  const dockerState = docker
    ? docker.running
      ? 'running'
      : docker.exists
        ? 'stopped'
        : docker.volume_exists
          ? 'missing (its data volume is still there)'
          : 'missing (its data volume is gone)'
    : null

  return (
    <CollapsibleSection title="Advanced">
      <div className="space-y-5 text-sm">
        <div className="space-y-1">
          <p className="font-medium text-fg">Connection</p>
          <p className="text-xs font-mono text-fg-muted break-all">
            {status.url}
          </p>
          <div className="flex items-center gap-2 pt-1">
            <Button
              size="sm"
              onClick={() => migrate.mutate()}
              disabled={migrate.isPending || status.migration.up_to_date}
            >
              {migrate.isPending ? 'Updating…' : 'Update database structure'}
            </Button>
            <span className="text-xs text-fg-muted">
              {status.migration.up_to_date
                ? 'Already up to date.'
                : `At ${status.migration.current_revision ?? 'no revision yet'}; latest is ${status.migration.head_revision}.`}
            </span>
          </div>
          {migrate.error && (
            <p role="alert" className="text-xs text-danger">
              {errorMessage(migrate.error)}
            </p>
          )}
        </div>

        {status.docker_managed && docker && (
          <div className="space-y-2">
            <p className="font-medium text-fg">Docker container</p>
            <p className="text-xs text-fg-muted">
              <span className="font-mono">{docker.name}</span> — {dockerState}
            </p>
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
              <Button
                size="sm"
                variant="danger"
                onClick={() => setConfirmTeardown(true)}
              >
                Remove container and its data…
              </Button>
            </div>
            {(setupDocker.error || teardown.error) && (
              <p role="alert" className="text-xs text-danger">
                {errorMessage(setupDocker.error ?? teardown.error)}
              </p>
            )}
          </div>
        )}

        <div className="space-y-2">
          <p className="font-medium text-fg">Use an existing database</p>
          <p className="text-xs text-fg-muted">
            Switches to a database that already holds your data, without copying
            anything. To carry this project&rsquo;s data into a different
            database, use <em>Move to another database</em> instead.
          </p>
          <Field label="Connection URL" hideLabel>
            <Input
              className="w-full font-mono"
              placeholder="postgresql+psycopg2://user:password@host:5432/dbname"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
            />
          </Field>
          {setUrl.error && (
            <p role="alert" className="text-xs text-danger">
              {errorMessage(setUrl.error)}
            </p>
          )}
          <Button
            size="sm"
            disabled={!urlInput.trim() || setUrl.isPending}
            onClick={() =>
              setUrl.mutate(urlInput.trim(), {
                onSuccess: () => setUrlInput(''),
              })
            }
          >
            {setUrl.isPending ? 'Testing…' : 'Test and switch'}
          </Button>
        </div>
      </div>

      {confirmTeardown && docker && (
        <ConfirmDialog
          title="Remove the Docker container?"
          variant="danger"
          body={
            <>
              This permanently deletes the container{' '}
              <span className="font-mono">{docker.name}</span> and the data
              inside it. If it holds your only copy of the project&rsquo;s data,
              that data is gone.
            </>
          }
          typedConfirmationValue={docker.name}
          confirmLabel="Delete container and data"
          isPending={teardown.isPending}
          onConfirm={() =>
            teardown.mutate(undefined, {
              onSuccess: () => setConfirmTeardown(false),
            })
          }
          onClose={() => setConfirmTeardown(false)}
        />
      )}
    </CollapsibleSection>
  )
}
