import { useEffect, useState } from 'react'
import type { CollectionFiles, RemoteStatus } from '../../api/remote'
import {
  useCollectionFiles,
  useFreeUp,
  useSetCollectionMode,
  useUpdateRemote,
} from '../../hooks/useRemote'
import { errorMessage } from '../../lib/errors'
import { formatSize } from '../../utils/storage'
import {
  Button,
  Card,
  ConfirmDialog,
  DataTable,
  SegmentedControl,
  Select,
} from '../ui'

const MODE_LABEL = {
  keep: 'Keep on this computer',
  opened: 'Fetch when opened',
}

/** Which files this computer keeps, per collection: a project default and a
 * choice per collection, how much of each is here and how much only on the
 * server, and freeing space by removing copies the server holds. */
export function SyncFilesCard({ s }: { s: RemoteStatus }) {
  const update = useUpdateRemote()
  const { data: rows, isLoading, error } = useCollectionFiles()
  const setMode = useSetCollectionMode()
  const [freeing, setFreeing] = useState<CollectionFiles | null>(null)
  const fallback = s.download_files === 'all' ? 'keep' : 'opened'

  return (
    <Card title="Files">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm text-fg-muted">By default</span>
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
      </div>
      <p className="mt-2 text-sm text-fg-muted">
        {s.files_to_fetch === 0
          ? 'Every file this computer keeps is here.'
          : `${s.files_to_fetch.toLocaleString()} file${s.files_to_fetch === 1 ? '' : 's'} this computer keeps ${s.files_to_fetch === 1 ? "isn't" : "aren't"} downloaded yet. They download in the background while Civex is running.`}
      </p>
      <DataTable
        className="mt-3"
        dense
        rows={rows ?? []}
        getRowId={(r) => r.id}
        isLoading={isLoading}
        error={error ? errorMessage(error) : undefined}
        emptyTitle="No collections"
        columns={[
          { key: 'name', header: 'Collection', render: (r) => r.name },
          {
            key: 'mode',
            header: 'Files',
            render: (r) => (
              <Select
                size="sm"
                aria-label={`Which of ${r.name}'s files this computer keeps`}
                value={r.chosen ? r.mode : ''}
                disabled={setMode.isPending}
                onChange={(e) =>
                  setMode.mutate({
                    id: r.id,
                    mode: (e.target.value || null) as 'keep' | 'opened' | null,
                  })
                }
              >
                <option value="">Default ({MODE_LABEL[fallback]})</option>
                <option value="keep">{MODE_LABEL.keep}</option>
                <option value="opened">{MODE_LABEL.opened}</option>
              </Select>
            ),
          },
          {
            key: 'here',
            header: 'On this computer',
            align: 'right',
            render: (r) =>
              `${r.files_here.toLocaleString()} · ${formatSize(r.bytes_here)}`,
          },
          {
            key: 'server',
            header: 'Only on the server',
            align: 'right',
            render: (r) => r.files_on_server.toLocaleString(),
          },
        ]}
        actions={(r) =>
          r.files_here > 0 ? (
            <Button size="sm" onClick={() => setFreeing(r)}>
              Free up space…
            </Button>
          ) : null
        }
        actionsLabel="Free up space"
      />
      {setMode.error && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {errorMessage(setMode.error)}
        </p>
      )}
      {freeing && (
        <FreeUpDialog collection={freeing} onClose={() => setFreeing(null)} />
      )}
    </Card>
  )
}

/** Counts first (asking the server which copies it holds), says what goes
 * and what stays and why, and removes exactly that on confirm. */
function FreeUpDialog({
  collection,
  onClose,
}: {
  collection: CollectionFiles
  onClose: () => void
}) {
  const count = useFreeUp()
  const free = useFreeUp()
  const { mutate } = count
  useEffect(() => {
    mutate({ id: collection.id, dryRun: true })
  }, [mutate, collection.id])
  const c = count.data
  const kept = [
    c?.kept_shared
      ? `${c.kept_shared.toLocaleString()} also used by a collection kept on this computer`
      : null,
    c?.not_on_server
      ? `${c.not_on_server.toLocaleString()} the server hasn't got yet`
      : null,
  ].filter(Boolean)
  const body = count.isPending ? (
    'Asking the server which of these files it holds…'
  ) : count.error ? (
    errorMessage(count.error)
  ) : !c || c.files === 0 ? (
    `Nothing to remove${kept.length ? `: keeps ${kept.join('; ')}.` : '.'}`
  ) : (
    <div className="space-y-2">
      <p>
        Removes this computer&apos;s copies of {c.files.toLocaleString()} file
        {c.files === 1 ? '' : 's'} ({formatSize(c.bytes)}). The server keeps
        them, and each comes back when it is opened or exported.
      </p>
      {kept.length > 0 && <p>Keeps {kept.join('; ')}.</p>}
      <p>
        {collection.name} is then set to fetch files when opened, so they
        aren&apos;t downloaded again in the background.
      </p>
    </div>
  )
  return (
    <ConfirmDialog
      title={`Free up space from ${collection.name}?`}
      body={body}
      confirmLabel={c ? `Remove ${formatSize(c.bytes)}` : 'Remove'}
      variant="danger"
      confirmDisabled={!c || c.files === 0}
      isPending={free.isPending}
      warning={free.error ? errorMessage(free.error) : undefined}
      onConfirm={() =>
        free.mutate(
          { id: collection.id, dryRun: false },
          { onSuccess: onClose },
        )
      }
      onClose={onClose}
    />
  )
}
