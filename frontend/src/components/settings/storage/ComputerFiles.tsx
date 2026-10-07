import { useEffect, useState } from 'react'
import type { FreeUp } from '../../../api/remote'
import {
  useCollectionFiles,
  useFreeUp,
  useRemoteStatus,
  useSetCollectionMode,
  useUpdateRemote,
} from '../../../hooks/useRemote'
import { errorMessage } from '../../../lib/errors'
import { formatSize } from '../../../utils/storage'
import {
  Button,
  ConfirmDialog,
  InfoTip,
  SegmentedControl,
  Select,
} from '../../ui'

/** The project's default for which files this computer keeps, and how many
 * kept files aren't downloaded yet. */
export function ComputerFilesDefault() {
  const { data: s } = useRemoteStatus()
  const update = useUpdateRemote()
  if (!s) return null
  return (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <span className="text-fg-muted">On this computer, by default</span>
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
      <span className="text-fg-muted">
        {s.files_to_fetch === 0
          ? 'Every file this computer keeps is here.'
          : `${s.files_to_fetch.toLocaleString()} file${s.files_to_fetch === 1 ? '' : 's'} this computer keeps ${s.files_to_fetch === 1 ? "isn't" : "aren't"} downloaded yet. They download in the background while Civex is running.`}
      </span>
    </div>
  )
}

const MODE_LABEL = { keep: 'Keep here', opened: 'Fetch when opened' }

/** One collection's choice of keeping its files on this computer, how many are
 * only on the server, and freeing its space. */
export function ComputerFilesCell({ collectionId }: { collectionId: string }) {
  const { data: s } = useRemoteStatus()
  const { data: rows } = useCollectionFiles()
  const setMode = useSetCollectionMode()
  const free = useFreeUp()
  const [freeing, setFreeing] = useState(false)
  const row = rows?.find((r) => r.id === collectionId)
  if (!s || !row) return null
  const fallback = s.download_files === 'all' ? 'keep' : 'opened'
  return (
    <div className="min-w-44 space-y-1">
      <Select
        size="sm"
        aria-label={`Which of ${row.name}'s files this computer keeps`}
        value={row.chosen ? row.mode : ''}
        disabled={setMode.isPending}
        onChange={(e) =>
          setMode.mutate({
            id: row.id,
            mode: (e.target.value || null) as 'keep' | 'opened' | null,
          })
        }
      >
        <option value="">Default ({MODE_LABEL[fallback]})</option>
        <option value="keep">{MODE_LABEL.keep}</option>
        <option value="opened">{MODE_LABEL.opened}</option>
      </Select>
      {row.files_here > 0 && (
        <Button size="sm" variant="link" onClick={() => setFreeing(true)}>
          Free up space…
        </Button>
      )}
      {freeing && (
        <FreeUpDialog
          what={row.name}
          willSwitch={row.mode === 'keep'}
          count={() => free.mutateAsync({ id: row.id, dryRun: true })}
          run={() => free.mutateAsync({ id: row.id, dryRun: false })}
          onClose={() => setFreeing(false)}
        />
      )}
    </div>
  )
}

/** Counts first (the server says which copies it holds), says what goes and
 * what stays and why, and removes exactly that on confirm. The one free-up
 * dialog: a collection's row and a Files tab selection both use it. */
export function FreeUpDialog({
  what,
  willSwitch = false,
  count,
  run,
  onClose,
}: {
  /** What is being freed, for the title ("Humpbacks", "12 files"). */
  what: string
  /** A collection kept here, which freeing sets to fetch when opened. */
  willSwitch?: boolean
  count: () => Promise<FreeUp>
  run: () => Promise<FreeUp>
  onClose: () => void
}) {
  const [counted, setCounted] = useState<FreeUp | null>(null)
  const [failed, setFailed] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let live = true
    count().then(
      (c) => live && setCounted(c),
      (e) => live && setFailed(e),
    )
    return () => {
      live = false
    }
    // Counted once, when the dialog opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const c = counted
  const kept = [
    c?.kept_shared
      ? `${c.kept_shared.toLocaleString()} in a collection kept on this computer`
      : null,
    c?.not_on_server
      ? `${c.not_on_server.toLocaleString()} the server hasn't got yet`
      : null,
  ].filter(Boolean)
  const body =
    failed && !c ? (
      errorMessage(failed)
    ) : !c ? (
      'Asking the server which of these files it holds…'
    ) : c.files === 0 ? (
      `Nothing to remove${kept.length ? `: keeps ${kept.join('; ')}.` : '.'}`
    ) : (
      <div className="space-y-2">
        <p>
          Removes this computer&apos;s copies of {c.files.toLocaleString()} file
          {c.files === 1 ? '' : 's'} ({formatSize(c.bytes)}). The server keeps
          them.
          <InfoTip>
            Each comes back when it is opened or exported.
            {willSwitch &&
              ` ${what} is then set to fetch files when opened, so they aren't downloaded again in the background.`}
          </InfoTip>
        </p>
        {kept.length > 0 && <p>Keeps {kept.join('; ')}.</p>}
      </div>
    )
  return (
    <ConfirmDialog
      title={`Free up space from ${what}?`}
      body={body}
      confirmLabel={c ? `Remove ${formatSize(c.bytes)}` : 'Remove'}
      variant="danger"
      confirmDisabled={!c || c.files === 0}
      isPending={busy}
      warning={c && failed ? errorMessage(failed) : undefined}
      onConfirm={() => {
        setBusy(true)
        run().then(onClose, (e) => {
          setFailed(e)
          setBusy(false)
        })
      }}
      onClose={onClose}
    />
  )
}
