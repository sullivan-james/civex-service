import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { settingsApi } from '../../api/settings'
import { errorMessage } from '../../lib/errors'
import type { RemoteStatus } from '../../api/remote'
import {
  useConnectRemote,
  useDisconnectRemote,
  useRemoteStatus,
  useSyncNow,
  useUpdateRemote,
} from '../../hooks/useRemote'
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  Field,
  Input,
  ProgressBar,
  SegmentedControl,
  Select,
  Skeleton,
  Spinner,
} from '../ui'
import { describeSyncProgress } from '../../utils/syncProgress'
import { SyncServing } from './SyncServing'

const INTERVALS = [
  { seconds: 0, label: 'Never' },
  { seconds: 15, label: 'Every 15 seconds' },
  { seconds: 60, label: 'Every minute' },
  { seconds: 300, label: 'Every 5 minutes' },
  { seconds: 900, label: 'Every 15 minutes' },
]

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : 'never'
}

function ConnectForm() {
  const connect = useConnectRemote()
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  return (
    <div className="max-w-xl space-y-3">
      <p className="text-sm text-fg-muted">
        Not following an authority. An empty project becomes a copy of it; a
        project with data fills an empty one.
      </p>
      <Field label="Authority address">
        <Input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://civex.example.com"
          className="font-mono"
        />
      </Field>
      <Field
        label="Device token"
        info="Issued on the authority with `civex sync device add`. It is stored on this computer, not in the project."
      >
        <Input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          autoComplete="off"
        />
      </Field>
      {connect.error && (
        <p role="alert" className="text-xs text-danger">
          {errorMessage(connect.error)}
        </p>
      )}
      <Button
        disabled={!url.trim() || !token.trim() || connect.isPending}
        onClick={() => connect.mutate({ url: url.trim(), token: token.trim() })}
      >
        {connect.isPending ? 'Connecting…' : 'Connect'}
      </Button>
    </div>
  )
}

function Conflicts({ count }: { count: number }) {
  if (count === 0) return null
  return (
    <Card
      title="Needs a look"
      count={count}
      action={
        <Button size="sm" variant="primary" to="/sync/review">
          Review
        </Button>
      }
    >
      <p className="text-xs text-fg-muted">
        These values did not go in as you made them. The authority’s value was
        kept; yours is saved here until you choose.
      </p>
    </Card>
  )
}

/** A copy going on (or one that stopped), above everything else: until it is
 * done the rest of the page describes a project that isn't whole yet. */
function Copying({ s }: { s: RemoteStatus }) {
  const again = useConnectRemote()
  if (s.progress) {
    const text = describeSyncProgress(s.progress)
    return (
      <Card title={text.title}>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          {text.fraction != null ? (
            <ProgressBar
              fraction={text.fraction}
              label={text.title}
              className="w-64"
            />
          ) : (
            <Spinner />
          )}
          <span className="text-fg-muted">{text.detail}</span>
        </div>
        {s.progress.phase === 'history' && (
          <p className="mt-2 text-xs text-fg-muted">
            The project is ready to use; this only fills in Activity.
          </p>
        )}
        {s.progress.phase === 'files' && (
          <p className="mt-2 text-xs text-fg-muted">
            Everything else works meanwhile; a file opened now is downloaded
            first.
          </p>
        )}
      </Card>
    )
  }
  if (s.connecting)
    return (
      <Card title="Connecting to the server">
        <Spinner />
      </Card>
    )
  if (!s.connect_error) return null
  return (
    <Card title="Connecting did not finish">
      <p role="alert" className="text-sm text-attention">
        {s.connect_error}
      </p>
      {again.error && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {errorMessage(again.error)}
        </p>
      )}
      <Button
        size="sm"
        className="mt-3"
        disabled={again.isPending || !s.remote}
        onClick={() => s.remote && again.mutate({ url: s.remote })}
      >
        Try again
      </Button>
    </Card>
  )
}

function Following({ s }: { s: RemoteStatus }) {
  const syncNow = useSyncNow()
  const update = useUpdateRemote()
  const disconnect = useDisconnectRemote()
  const [confirm, setConfirm] = useState(false)
  const interval = INTERVALS.some((i) => i.seconds === s.interval_seconds)
    ? s.interval_seconds
    : 60
  return (
    <div className="max-w-2xl space-y-5">
      <Copying s={s} />
      <Card title="Authority">
        <dl className="grid grid-cols-[8rem_1fr] gap-y-1 text-sm">
          <dt className="text-fg-muted">Address</dt>
          <dd className="font-mono break-all">{s.remote}</dd>
          <dt className="text-fg-muted">Last synced</dt>
          <dd>{when(s.last_synced_at)}</dd>
          <dt className="text-fg-muted">Not yet sent</dt>
          <dd>{s.pending}</dd>
          <dt className="text-fg-muted">State</dt>
          <dd>
            {s.running ? (
              <Badge variant="accent">Syncing</Badge>
            ) : s.paused ? (
              <Badge>Paused</Badge>
            ) : s.last_error ? (
              <Badge variant="attention">Could not sync</Badge>
            ) : s.pending > 0 ? (
              <Badge variant="attention">
                {s.pending} change{s.pending === 1 ? '' : 's'} waiting to send
              </Badge>
            ) : (
              <Badge variant="success">Up to date</Badge>
            )}
          </dd>
        </dl>
        {s.last_error && (
          <p role="alert" className="mt-2 text-xs text-attention">
            {s.last_error} ({when(s.last_error_at)}). It tries again by itself.
          </p>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="primary"
            disabled={syncNow.isPending || s.running}
            onClick={() => syncNow.mutate()}
          >
            Sync now
          </Button>
          <Button
            size="sm"
            disabled={update.isPending}
            onClick={() => update.mutate({ paused: !s.paused })}
          >
            {s.paused ? 'Resume' : 'Pause'}
          </Button>
          <Select
            size="sm"
            aria-label="How often to look for changes"
            value={interval}
            onChange={(e) =>
              update.mutate({ interval_seconds: Number(e.target.value) })
            }
          >
            {INTERVALS.map((i) => (
              <option key={i.seconds} value={i.seconds}>
                {i.label}
              </option>
            ))}
          </Select>
          <Button size="sm" variant="danger" onClick={() => setConfirm(true)}>
            Disconnect
          </Button>
        </div>
      </Card>
      <FilesCard s={s} />
      <Conflicts count={s.open_conflicts} />
      {confirm && (
        <ConfirmDialog
          title="Stop following this authority?"
          body="The data stays here as it is. Changes made from now on are no longer sent anywhere."
          confirmLabel="Disconnect"
          variant="danger"
          isPending={disconnect.isPending}
          onConfirm={() =>
            disconnect.mutate(undefined, { onSuccess: () => setConfirm(false) })
          }
          onClose={() => setConfirm(false)}
        />
      )}
    </div>
  )
}

/** Which files this computer keeps a copy of, and how many aren't here yet. */
function FilesCard({ s }: { s: RemoteStatus }) {
  const update = useUpdateRemote()
  const all = s.download_files === 'all'
  const n = s.files_to_fetch
  return (
    <Card title="Files">
      <SegmentedControl
        size="sm"
        label="Which files this computer keeps"
        value={s.download_files}
        onChange={(v) => update.mutate({ download_files: v })}
        options={[
          { value: 'all', label: 'Keep every file' },
          { value: 'opened', label: 'Only files I open' },
        ]}
      />
      <p className="mt-2 text-sm text-fg-muted">
        {n === 0
          ? 'Every file the records here use is on this computer.'
          : `${n.toLocaleString()} file${n === 1 ? '' : 's'} not downloaded yet. ` +
            (all
              ? 'They download in the background while Civex is running.'
              : 'Each downloads when it is opened or exported.')}
      </p>
      {update.error && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {errorMessage(update.error)}
        </p>
      )}
    </Card>
  )
}

function NameCard() {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['settings', 'identity'],
    queryFn: settingsApi.getIdentity,
  })
  const save = useMutation({
    mutationFn: (name: string | null) => settingsApi.updateIdentity(name),
    onSuccess: (saved) => qc.setQueryData(['settings', 'identity'], saved),
  })
  const [draft, setDraft] = useState<string | null>(null)
  if (!data) return null
  const value = draft ?? data.chosen ?? ''
  return (
    <Card title="Author">
      <div className="flex items-end gap-2">
        <Field
          label="Author name"
          info={`Recorded with each change you make in this project. Left empty, it is your computer's user name (${data.default ?? 'unknown'}).`}
        >
          <Input
            value={value}
            placeholder={data.default ?? ''}
            onChange={(e) => setDraft(e.target.value)}
            className="max-w-xs"
          />
        </Field>
        <Button
          size="sm"
          disabled={save.isPending || value === (data.chosen ?? '')}
          onClick={() =>
            save.mutate(value.trim() || null, {
              onSuccess: () => setDraft(null),
            })
          }
        >
          Save
        </Button>
      </div>
    </Card>
  )
}

export default function SyncSection() {
  const { data } = useRemoteStatus()
  if (!data) return <Skeleton className="h-9 w-80" />
  return (
    <div className="space-y-5">
      {data.configured || data.connecting ? (
        <Following s={data} />
      ) : (
        <ConnectForm />
      )}
      <div className="max-w-2xl space-y-5">
        <SyncServing />
        <NameCard />
      </div>
    </div>
  )
}
