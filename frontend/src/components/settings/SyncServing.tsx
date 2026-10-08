import { useState } from 'react'
import type { LibraryMode, SyncDevice, SyncInvite } from '../../api/remote'
import { useAuthority, useAuthorityActions } from '../../hooks/useRemote'
import { errorMessage } from '../../lib/errors'
import {
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  DataTable,
  Field,
  Input,
  SegmentedControl,
  type DataTableColumn,
} from '../ui'

const LIBRARY_MODES: { value: LibraryMode; label: string }[] = [
  { value: 'off', label: 'Nothing' },
  { value: 'workflows', label: 'Workflows' },
  { value: 'all', label: 'Workflows and plugins' },
]

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : 'never'
}

const DEVICES: DataTableColumn<SyncDevice>[] = [
  { key: 'name', header: 'Device', render: (d) => d.name },
  {
    key: 'key',
    header: 'Key',
    render: (d) => <span className="font-mono">{d.fingerprint}</span>,
  },
  { key: 'seen', header: 'Last synced', render: (d) => when(d.last_seen_at) },
  {
    key: 'state',
    header: 'State',
    render: (d) => (d.revoked ? 'Revoked' : 'Active'),
  },
]

const INVITES: DataTableColumn<SyncInvite>[] = [
  { key: 'name', header: 'Invited', render: (i) => i.name },
  { key: 'until', header: 'Works until', render: (i) => when(i.expires_at) },
]

/** This project as an authority: whether other copies may follow it, the
 * devices that joined and the invites waiting. The same as `civex sync
 * authority` and `civex sync device`, through the same calls. */
export function SyncServing() {
  const { data } = useAuthority()
  const {
    setServing,
    invite,
    cancelInvite,
    revokeDevice,
    setLibrary,
    allowPublish,
  } = useAuthorityActions()
  const [name, setName] = useState('')
  const [issued, setIssued] = useState<{ name: string; invite: string } | null>(
    null,
  )
  const [revoking, setRevoking] = useState<string | null>(null)
  if (!data) return null
  const failure =
    setServing.error ??
    invite.error ??
    cancelInvite.error ??
    revokeDevice.error ??
    setLibrary.error ??
    allowPublish.error
  const devices: DataTableColumn<SyncDevice>[] = [
    ...DEVICES,
    {
      key: 'publish',
      header: 'May publish',
      render: (d) =>
        d.revoked ? null : (
          <Checkbox
            checked={d.may_publish}
            disabled={allowPublish.isPending || data.library === 'off'}
            aria-label={`${d.name} may publish to the library`}
            onChange={(e) =>
              allowPublish.mutate({ name: d.name, allowed: e.target.checked })
            }
          />
        ),
    },
  ]

  return (
    <Card
      title="Other devices following this project"
      info="A device joins with an invite that works once, then signs in with a key that never leaves it."
      action={
        <Button
          size="sm"
          variant={data.serving ? 'default' : 'primary'}
          disabled={setServing.isPending}
          onClick={() => setServing.mutate(!data.serving)}
        >
          {data.serving ? 'Stop accepting devices' : 'Accept devices'}
        </Button>
      }
    >
      <div className="space-y-4 text-sm">
        {!data.serving && (
          <p className="text-fg-muted">No device can follow this project.</p>
        )}
        {data.fingerprint && (
          <p className="text-fg-muted">
            This authority's key:{' '}
            <span className="font-mono text-fg">{data.fingerprint}</span>
          </p>
        )}
        {data.devices.length > 0 && (
          <DataTable
            columns={devices}
            rows={data.devices}
            getRowId={(d) => `${d.name}-${d.created_at}`}
            dense
            actions={(d) =>
              d.revoked ? null : (
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => setRevoking(d.name)}
                >
                  Revoke
                </Button>
              )
            }
          />
        )}
        {data.serving && (
          <Field
            label="Devices may share"
            info="Ticked devices may publish to the library, for others to install. Plugins are code: whoever installs one runs it."
          >
            <SegmentedControl
              label="What devices may share"
              size="sm"
              options={LIBRARY_MODES}
              value={data.library}
              onChange={(mode) => setLibrary.mutate(mode)}
            />
          </Field>
        )}
        {data.invites.length > 0 && (
          <DataTable
            columns={INVITES}
            rows={data.invites}
            getRowId={(i) => i.name}
            dense
            actions={(i) => (
              <Button
                size="sm"
                disabled={cancelInvite.isPending}
                onClick={() => cancelInvite.mutate(i.name)}
              >
                Cancel
              </Button>
            )}
          />
        )}
        {data.serving && (
          <div className="flex items-end gap-2">
            <Field label="New device">
              <Input
                value={name}
                placeholder="e.g. field laptop"
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Button
              size="sm"
              disabled={!name.trim() || invite.isPending}
              onClick={() =>
                invite.mutate(name.trim(), {
                  onSuccess: (r) => {
                    setIssued({ name: name.trim(), invite: r.invite })
                    setName('')
                  },
                })
              }
            >
              Invite
            </Button>
          </div>
        )}
        {issued && (
          <div
            role="status"
            className="space-y-1 rounded border border-border p-3"
          >
            <p>
              Invite for <strong>{issued.name}</strong>. Copy it now: it is not
              shown again, and it works once.
            </p>
            <code className="block break-all font-mono text-xs">
              {issued.invite}
            </code>
            <Button
              size="sm"
              onClick={() => void navigator.clipboard?.writeText(issued.invite)}
            >
              Copy
            </Button>
          </div>
        )}
        {failure && (
          <p role="alert" className="text-xs text-danger">
            {errorMessage(failure)}
          </p>
        )}
      </div>
      {revoking && (
        <ConfirmDialog
          title={`Revoke ${revoking}?`}
          body="It can't sync from now on. Changes it has not sent stay on that device."
          confirmLabel="Revoke"
          variant="danger"
          isPending={revokeDevice.isPending}
          onConfirm={() =>
            revokeDevice.mutate(revoking, {
              onSettled: () => setRevoking(null),
            })
          }
          onClose={() => setRevoking(null)}
        />
      )}
    </Card>
  )
}
