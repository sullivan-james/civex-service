import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { settingsApi } from '../../api/settings'
import { errorMessage } from '../../lib/errors'
import type { RemoteStatus, SyncConflict } from '../../api/remote'
import {
  useConnectRemote,
  useDisconnectRemote,
  useRemoteStatus,
  useResolveConflict,
  useSyncConflicts,
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
  Select,
  Skeleton,
} from '../ui'

const INTERVALS = [
  { seconds: 0, label: 'Never (only when I press Sync now)' },
  { seconds: 15, label: 'Every 15 seconds' },
  { seconds: 60, label: 'Every minute' },
  { seconds: 300, label: 'Every 5 minutes' },
  { seconds: 900, label: 'Every 15 minutes' },
]

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : 'never'
}

function show(value: unknown): string {
  if (value === null || value === undefined) return 'nothing'
  return typeof value === 'string' ? value : JSON.stringify(value)
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

function ConflictRow({ c }: { c: SyncConflict }) {
  const resolve = useResolveConflict()
  const settleable = c.kind === 'conflict'
  return (
    <li className="space-y-2 border-b border-border py-3 last:border-0">
      <div className="text-sm">
        {c.message ??
          `${c.field ?? 'A value'} on a ${c.entity_type} was changed on both sides.`}
      </div>
      {settleable && (
        <div className="grid gap-1 text-xs sm:grid-cols-2">
          <div>
            <span className="text-fg-muted">Yours: </span>
            <span className="font-mono">{show(c.yours)}</span>
          </div>
          <div>
            <span className="text-fg-muted">Kept: </span>
            <span className="font-mono">{show(c.theirs)}</span>
          </div>
        </div>
      )}
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={resolve.isPending}
          onClick={() => resolve.mutate({ id: c.id, take: 'theirs' })}
        >
          {settleable ? 'Keep theirs' : 'Dismiss'}
        </Button>
        {settleable && (
          <Button
            size="sm"
            disabled={resolve.isPending}
            onClick={() => resolve.mutate({ id: c.id, take: 'mine' })}
          >
            Use mine
          </Button>
        )}
      </div>
      {resolve.error && (
        <p role="alert" className="text-xs text-danger">
          {errorMessage(resolve.error)}
        </p>
      )}
    </li>
  )
}

function Conflicts({ count }: { count: number }) {
  const { data = [] } = useSyncConflicts(count > 0)
  if (count === 0) return null
  return (
    <Card title="Needs a look" count={count}>
      <p className="text-xs text-fg-muted">
        These values did not go in as you made them. The authority’s value was
        kept; yours is saved here until you choose.
      </p>
      <ul>
        {data.map((c) => (
          <ConflictRow key={c.id} c={c} />
        ))}
      </ul>
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
  const manualOnly = s.interval_seconds === 0
  return (
    <div className="max-w-2xl space-y-5">
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
            ) : manualOnly && s.pending === 0 ? (
              <Badge>Only when asked</Badge>
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
    <Card title="Your name on changes">
      <p className="mb-2 text-xs text-fg-muted">
        Recorded with every change made in this project, like git’s user name.
        Left empty it is your computer’s user name ({data.default ?? 'unknown'}
        ). It is saved in this project’s settings file.
      </p>
      <div className="flex items-center gap-2">
        <Input
          aria-label="Your name on changes"
          value={value}
          placeholder={data.default ?? ''}
          onChange={(e) => setDraft(e.target.value)}
          className="max-w-xs"
        />
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
      {data.configured ? <Following s={data} /> : <ConnectForm />}
      <div className="max-w-2xl">
        <NameCard />
      </div>
    </div>
  )
}
