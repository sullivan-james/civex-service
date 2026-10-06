import { useState } from 'react'
import type { SyncDevice } from '../../api/remote'
import { useAuthority, useAuthorityActions } from '../../hooks/useRemote'
import { errorMessage } from '../../lib/errors'
import {
  Button,
  Card,
  ConfirmDialog,
  DataTable,
  Field,
  Input,
  type DataTableColumn,
} from '../ui'

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : 'never'
}

const COLUMNS: DataTableColumn<SyncDevice>[] = [
  { key: 'name', header: 'Device', render: (d) => d.name },
  { key: 'seen', header: 'Last synced', render: (d) => when(d.last_seen_at) },
  {
    key: 'state',
    header: 'Token',
    render: (d) => (d.revoked ? 'Revoked' : 'Active'),
  },
]

/** This project as an authority: whether other copies may follow it, and the
 * devices issued a token. The same as `civex sync authority` and `civex sync
 * device`, through the same calls. */
export function SyncServing() {
  const { data } = useAuthority()
  const { setServing, addDevice, revokeDevice } = useAuthorityActions()
  const [name, setName] = useState('')
  const [issued, setIssued] = useState<{ name: string; token: string } | null>(
    null,
  )
  const [revoking, setRevoking] = useState<string | null>(null)
  if (!data) return null
  const failure = setServing.error ?? addDevice.error ?? revokeDevice.error

  return (
    <Card
      title="Other devices following this project"
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
        <p className="text-fg-muted">
          {data.serving
            ? 'Devices with a token can copy this project and keep in step with it while the app is running.'
            : 'No device can follow this project. Accept devices to let other copies keep in step with this one.'}
        </p>
        {data.devices.length > 0 && (
          <DataTable
            columns={COLUMNS}
            rows={data.devices}
            getRowId={(d) => d.name}
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
              disabled={!name.trim() || addDevice.isPending}
              onClick={() =>
                addDevice.mutate(name.trim(), {
                  onSuccess: (r) => {
                    setIssued({ name: name.trim(), token: r.token })
                    setName('')
                  },
                })
              }
            >
              Issue a token
            </Button>
          </div>
        )}
        {issued && (
          <div
            role="status"
            className="space-y-1 rounded border border-border p-3"
          >
            <p>
              Token for <strong>{issued.name}</strong>. Copy it now: it is not
              shown again. On that device, connect with this project's address
              and this token.
            </p>
            <code className="block break-all font-mono text-xs">
              {issued.token}
            </code>
            <Button
              size="sm"
              onClick={() => void navigator.clipboard?.writeText(issued.token)}
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
          body="Its token stops working at once. Changes it has not sent stay on that device."
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
