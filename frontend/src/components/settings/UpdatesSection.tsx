import type { UpdateAttempt, UpdateStatus } from '../../api/updates'
import {
  usePreReleases,
  useUpdateStatus,
  writeUpdatePref,
} from '../../hooks/useUpdate'
import { formatDateTime } from '../../utils/dates'
import {
  clearRestartProblem,
  restartForUpdate,
  useRestartPhase,
  type RestartPhase,
} from '../../utils/updateRestart'
import { Button, Checkbox, Field, Skeleton, Spinner, Status } from '../ui'

function Availability({ status }: { status: UpdateStatus }) {
  if (status.error)
    return (
      <Status tone="attention" why={status.error}>
        Couldn’t check for updates
      </Status>
    )
  if (!status.newer)
    return <Status tone="ok">civex {status.current} is up to date</Status>
  return (
    <Status tone="attention" why={status.blocked || undefined}>
      civex {status.latest} is available
    </Status>
  )
}

function LastUpdate({ last }: { last: UpdateAttempt }) {
  const when = formatDateTime(last.at)
  if (last.ok)
    return (
      <Status tone="ok">
        Updated from {last.from_version} to {last.to_version} on {when}
      </Status>
    )
  return (
    <Status tone="danger" why={last.message}>
      The update on {when} didn’t install a new version
    </Status>
  )
}

function Restarting({ phase }: { phase: RestartPhase }) {
  if (phase.kind === 'closing' || phase.kind === 'restarting')
    return (
      <p
        role="status"
        className="flex items-center gap-2 text-sm text-fg-muted"
      >
        <Spinner />
        {phase.kind === 'closing'
          ? 'Closing civex to update…'
          : 'Updating civex. This page reloads when it’s back.'}
      </p>
    )
  if (phase.kind === 'timeout')
    return (
      <Status
        tone="danger"
        why="It may still be updating, or it may not have started again. Start civex yourself; the log is update.log in the .civex folder in your home folder."
      >
        civex hasn’t come back
      </Status>
    )
  if (phase.kind === 'failed')
    return (
      <Status tone="danger" why={phase.message}>
        civex couldn’t start the update
      </Status>
    )
  return null
}

export default function UpdatesSection() {
  const [pre, setPre] = usePreReleases()
  const { data: status, isFetching, refetch } = useUpdateStatus(pre)
  const phase = useRestartPhase()
  const busy = phase.kind === 'closing' || phase.kind === 'restarting'

  return (
    <div className="max-w-xl space-y-4">
      {!status ? (
        <Skeleton className="h-6 w-64" />
      ) : (
        <div className="space-y-2">
          <Availability status={status} />
          {status.newer && !status.error && status.blocked && (
            <p className="text-sm text-fg-muted">{status.blocked}</p>
          )}
          {status.last && <LastUpdate last={status.last} />}
        </div>
      )}

      <Field
        label="Pre-releases"
        info="Release candidates, for trying what’s coming before it is final. They are only offered while this is on; once on one, you move to the final release when it’s out."
      >
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={pre}
            onChange={(e) => setPre(e.target.checked)}
            disabled={busy}
          />
          Include pre-releases
        </label>
      </Field>

      <Restarting phase={phase} />

      <div className="flex flex-wrap gap-2">
        {status?.newer && status.can_update && !status.error && (
          <Button
            variant="primary"
            disabled={busy}
            onClick={() => {
              writeUpdatePref('later', null)
              void restartForUpdate(pre)
            }}
          >
            Update to {status.latest} and restart
          </Button>
        )}
        <Button
          disabled={busy || isFetching}
          onClick={() => {
            clearRestartProblem()
            void refetch()
          }}
        >
          {isFetching ? 'Checking…' : 'Check again'}
        </Button>
      </div>
    </div>
  )
}
