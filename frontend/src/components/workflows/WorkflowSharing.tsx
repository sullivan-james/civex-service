import { useState } from 'react'
import type { LibraryItem, LibraryVersion } from '../../api/remote'
import { useLibraryActions } from '../../hooks/useRemote'
import { errorMessage } from '../../lib/errors'
import {
  sharingLabel,
  sharingState,
  type WorkflowRow,
} from '../../utils/workflowSharing'
import {
  Badge,
  Button,
  ConfirmDialog,
  DataTable,
  EmptyState,
  type DataTableColumn,
} from '../ui'
import { LibraryInstallDialog } from './LibraryInstallDialog'
import { PublishDialog } from './PublishDialog'

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : ''
}

function pinsText(pins: Record<string, number>): string {
  const entries = Object.entries(pins)
  return entries.length
    ? entries.map(([id, v]) => `${id} v${v}`).join(', ')
    : '—'
}

/** How a workflow stands with the library, and every version of it there:
 * install the newest, roll back to an earlier one, publish what is here, or
 * take a version out. A version installs the plugin versions it was
 * published with. */
export function WorkflowSharing({
  row,
  sharing,
  library,
}: {
  row: WorkflowRow
  sharing: boolean
  /** Everything in the library, to say how its plugins stand here. */
  library: LibraryItem[]
}) {
  const [installing, setInstalling] = useState<number | 'newest' | null>(null)
  const [publishing, setPublishing] = useState(false)
  const [removing, setRemoving] = useState<number | null>(null)
  const { unpublish } = useLibraryActions()

  if (!sharing) {
    return (
      <EmptyState
        title="Nothing to share with"
        message="Workflows are shared through a server. Connect to one, or serve this project, in Settings › Sync."
      />
    )
  }

  const shared = row.shared
  const state = sharingState(row)
  const { label, variant } = sharingLabel(row)
  const plugins = new Map(
    library
      .filter((i) => i.kind === 'plugin' && i.provides)
      .map((i) => [i.provides!, i]),
  )
  const here = shared?.local_version ?? null

  const columns: DataTableColumn<LibraryVersion>[] = [
    {
      key: 'version',
      header: 'Version',
      render: (v) => (
        <span className="inline-flex items-center gap-2">
          v{v.version}
          {v.version === here && <Badge variant="success">Here</Badge>}
        </span>
      ),
    },
    {
      key: 'by',
      header: 'Published',
      render: (v) => (
        <span className="text-sm">
          {v.published_by ?? 'unknown'}
          <span className="block text-xs text-fg-muted">
            {when(v.published_at)}
          </span>
        </span>
      ),
    },
    {
      key: 'pins',
      header: 'Plugins it uses',
      render: (v) => (
        <span className="font-mono text-xs text-fg-muted">
          {pinsText(v.pins)}
        </span>
      ),
    },
  ]

  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <Badge variant={variant}>{label}</Badge>
        {row.local && (state === 'not-shared' || state === 'changed') && (
          <Button
            size="sm"
            variant="primary"
            onClick={() => setPublishing(true)}
          >
            {state === 'changed' ? 'Publish changes…' : 'Publish…'}
          </Button>
        )}
        {(state === 'update' || state === 'library') && (
          <Button
            size="sm"
            variant="primary"
            onClick={() => setInstalling('newest')}
          >
            {state === 'update' ? `Update to v${shared?.version}…` : 'Install…'}
          </Button>
        )}
      </div>

      {shared && shared.needs.length > 0 && (
        <div>
          <h3 className="mb-1 text-sm font-semibold text-fg">
            Plugins v{shared.version} uses
          </h3>
          <ul className="space-y-1">
            {shared.needs.map((id) => {
              const plugin = plugins.get(id)
              const pinned = shared.pins[id]
              const local = plugin?.local_version
              return (
                <li key={id} className="flex flex-wrap items-center gap-2">
                  <span className="font-mono">{id}</span>
                  <span className="text-fg-muted">
                    {pinned ? `v${pinned}` : 'any version'}
                    {plugin && plugin.version !== pinned
                      ? ` (the library has up to v${plugin.version})`
                      : ''}
                  </span>
                  {local ? (
                    <Badge variant={local === pinned ? 'success' : 'attention'}>
                      v{local} here
                    </Badge>
                  ) : plugin?.here === 'different' ? (
                    <Badge variant="attention">Changed here</Badge>
                  ) : (
                    <Badge>Not here</Badge>
                  )}
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {shared && (
        <DataTable
          dense
          columns={columns}
          rows={shared.history}
          getRowId={(v) => String(v.version)}
          emptyTitle="No versions"
          actions={(v) => (
            <span className="inline-flex gap-1">
              {v.version !== here && (
                <Button size="sm" onClick={() => setInstalling(v.version)}>
                  {here && v.version < here
                    ? 'Roll back…'
                    : here
                      ? 'Update…'
                      : 'Install…'}
                </Button>
              )}
              <Button
                size="sm"
                variant="danger"
                onClick={() => setRemoving(v.version)}
              >
                Remove
              </Button>
            </span>
          )}
          actionsLabel="Actions"
          actionsWidth="180px"
        />
      )}

      {installing !== null && (
        <LibraryInstallDialog
          kind="workflow"
          name={row.stem}
          version={installing === 'newest' ? null : installing}
          onClose={() => setInstalling(null)}
        />
      )}
      {publishing && row.local && (
        <PublishDialog
          stem={row.stem}
          name={row.name}
          sharedVersion={shared?.version ?? null}
          onClose={() => setPublishing(false)}
        />
      )}
      {removing !== null && (
        <ConfirmDialog
          title={`Remove v${removing} of ${row.name} from the library?`}
          body="Computers that installed it keep their copy."
          confirmLabel="Remove"
          variant="danger"
          isPending={unpublish.isPending}
          warning={unpublish.error ? errorMessage(unpublish.error) : undefined}
          onClose={() => {
            unpublish.reset()
            setRemoving(null)
          }}
          onConfirm={() =>
            unpublish.mutate(
              {
                kind: 'workflow',
                name: row.stem,
                version: removing,
                force: false,
              },
              { onSuccess: () => setRemoving(null) },
            )
          }
        />
      )}
    </div>
  )
}
