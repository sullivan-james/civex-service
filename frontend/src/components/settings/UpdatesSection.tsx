import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { settingsApi } from '../../api/settings'
import type { UpdateAttempt, UpdateStatus } from '../../api/updates'
import { errorMessage } from '../../lib/errors'
import {
  useDismissLastUpdate,
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
import {
  Button,
  Checkbox,
  Field,
  Skeleton,
  Spinner,
  Status,
  Subheading,
} from '../ui'

/** The desktop app's civex as a terminal command: shown only in the desktop
 * app (a uv, pipx or pip install already is one). */
function CommandLine() {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['command-line'],
    queryFn: settingsApi.getCommandLine,
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  if (!data?.available) return null

  async function change(add: boolean) {
    setBusy(true)
    setError(null)
    try {
      const next = add
        ? await settingsApi.addCommandLine()
        : await settingsApi.removeCommandLine()
      qc.setQueryData(['command-line'], next)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const why = data.shadowed_by
    ? `A terminal finds another civex first: ${data.shadowed_by}`
    : data.note || undefined
  return (
    <div className="space-y-2">
      <Subheading>Command line</Subheading>
      {data.on_path ? (
        <Status
          tone={data.shadowed_by || data.note ? 'attention' : 'ok'}
          why={why}
        >
          `civex` works in a terminal
        </Status>
      ) : (
        <Status
          tone="neutral"
          why="Adds this app's civex to your PATH, for you only. Remove it here, or by uninstalling the app."
        >
          `civex` isn’t a terminal command yet
        </Status>
      )}
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
      <Button disabled={busy} onClick={() => void change(!data.on_path)}>
        {data.on_path ? 'Remove from PATH' : 'Add to PATH'}
      </Button>
    </div>
  )
}

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
  const dismiss = useDismissLastUpdate()
  return (
    <div className="flex flex-wrap items-center gap-2">
      {last.ok ? (
        <Status tone="ok">
          Updated from {last.from_version} to {last.to_version} on {when}
        </Status>
      ) : (
        <Status tone="danger" why={last.message}>
          The update on {when} didn’t install a new version
        </Status>
      )}
      <Button
        size="sm"
        variant="link"
        disabled={dismiss.isPending}
        onClick={() => dismiss.mutate()}
      >
        Dismiss
      </Button>
    </div>
  )
}

/** The other servers running from this copy, which updating stops and starts
 * again (they hold its files, and would run the old version). */
function RunningAlongside({ running }: { running: string[] }) {
  return (
    <div className="space-y-1 text-sm">
      <p className="text-fg-muted">
        Also running from this copy of civex. Updating stops{' '}
        {running.length === 1 ? 'it' : 'them'} and starts{' '}
        {running.length === 1 ? 'it' : 'them'} again afterwards:
      </p>
      <ul className="list-disc space-y-0.5 pl-5 font-mono text-xs">
        {running.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
    </div>
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
          {status.newer && status.can_update && status.running.length > 0 && (
            <RunningAlongside running={status.running} />
          )}
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
              void restartForUpdate({
                pre,
                version: status.latest,
                stopOthers: status.running.length > 0,
              })
            }}
          >
            {status.running.length > 0
              ? `Stop ${status.running.length === 1 ? 'it' : 'them'}, update to ${status.latest} and restart`
              : `Update to ${status.latest} and restart`}
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

      <CommandLine />
    </div>
  )
}
