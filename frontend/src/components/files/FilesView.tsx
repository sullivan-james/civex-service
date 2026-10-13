import { useState } from 'react'
import { Link } from 'react-router'
import type {
  FilePick,
  FileUse,
  FileSelection,
  FileListing,
  ListedFile,
  PlaceSummary,
  ServerState,
} from '../../api/fileAccess'
import { useListParams } from '../../hooks/useListParams'
import {
  useFollowsServer,
  useRemoteStatus,
  useSendFilesNow,
} from '../../hooks/useRemote'
import { useSchemas } from '../../hooks/useSchemas'
import { useQueryClient } from '@tanstack/react-query'
import { useFileListing, useFreeUpFiles } from '../../hooks/useFileListing'
import { useFileInfo } from '../../hooks/useFiles'
import { errorMessage } from '../../lib/errors'
import { displayLabel } from '../../utils/naming'
import { PLACE_TONE, placeLabel } from '../../utils/places'
import { PlaceStatus, PlacesBar } from './Where'
import { formatSize } from '../../utils/storage'
import { FileLink } from '../records/FileLocation'
import { DeletedKeepers } from '../records/FileInfoPanel'
import { SelectionBar } from '../explorer/SelectionBar'
import { useBulkSelection } from '../../hooks/useBulkSelection'
import { FreeUpDialog } from '../settings/storage/ComputerFiles'
import {
  Button,
  Chip,
  StatusDot,
  DataTable,
  MultiPick,
  Pagination,
  TriggerPopover,
  useToast,
} from '../ui'
import { ProgressBar } from '../ui/ProgressBar'
import { describeSyncProgress } from '../../utils/syncProgress'
import { downloadFiles, type FlowContext } from './fileFlows'
import { MoveToDriveButton } from './MoveDialog'

const NS = 'files.'

/** What the records explorer is listing, as files: the files of those records
 * and of everything beneath them, under the explorer's own filters (any
 * condition, on any level), search and saved view, so there is nothing to set
 * twice. Here it adds where each file is (the places bar, a filter by place),
 * ticks with "all N matching", and what to do with them: move them onto a
 * drive, download them from the server, or free this computer's space. What is
 * listed is exactly what an action takes (the server picks both by the same
 * rule). */
export function FilesView({
  selection,
  search,
}: {
  selection: FileSelection
  /** The explorer's search box: a file's name, or any record's it sits under. */
  search?: string
}) {
  const list = useListParams(NS, ['place', 'kind', 'used', 'server'], 50)
  const { data: schemas = [] } = useSchemas()
  const followsServer = useFollowsServer()
  const [acting, setActing] = useState<'free' | null>(null)
  const toast = useToast()
  const qc = useQueryClient()
  // Moving and downloading run as file jobs: progress in the status bar, and
  // they carry on if the page is left.
  const flow: FlowContext = { toast, qc, problem: () => undefined }
  const free = useFreeUpFiles()

  // Kinds of file (file fields), several at once, kept in the address.
  const chosenKinds = list.picks.kind ? list.picks.kind.split(',') : []
  // How many records use a file, several at once ("used by 2 or 3").
  const chosenUses = list.picks.used
    ? list.picks.used.split(',').map(Number)
    : []
  const pick: FilePick = {
    ...selection,
    fields: chosenKinds.length ? chosenKinds : selection.fields,
    place: list.picks.place || undefined,
    name: search || undefined,
    used_by: chosenUses.length ? chosenUses : undefined,
    server: (list.picks.server as ServerState) || undefined,
  }
  const order = list.sort
    ? `${list.sort.dir === 'desc' ? '-' : ''}${list.sort.field}`
    : 'path'
  const { data, isLoading, isFetching, error } = useFileListing({
    ...pick,
    order,
    offset: list.page * list.size,
    limit: list.size,
  })
  const rows = data?.items ?? []
  const total = data?.total ?? 0

  // The same ticks as the records list: rows, ranges, the page box, and "all N
  // matching" (every file the filters match, on every page).
  const picked = useBulkSelection(
    rows.map((r) => r.sha256),
    JSON.stringify([pick, order, list.page, list.size]),
  )
  // "All matching" takes the filters as they are; ticks take those files (a
  // row is a file as stored, with every record here that uses it).
  const target: FilePick = picked.allMatching
    ? pick
    : { ...pick, shas: [...picked.selected] }
  const count = picked.count(total)
  const what = `${count.toLocaleString()} file${count === 1 ? '' : 's'}`

  // A kind of file is a file field ("Selection table"): named as the field is.
  const kindLabel = (name: string) => {
    const f = schemas.flatMap((s) => s.fields).find((x) => x.name === name)
    return displayLabel(name, f?.label)
  }
  const kinds = data?.kinds ?? []
  const sharing = data?.sharing ?? []

  return (
    <div className="space-y-4">
      {/* Which files: of what kind, and where. One row, then where they all
          are as a bar; the table and what to do with it follow. */}
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          {kinds.length > 1 && (
            <MultiPick
              label="Kinds of file"
              value={chosenKinds}
              onChange={(next) =>
                list.set({ kind: next.length ? next.join(',') : undefined })
              }
              options={kinds.map((k) => ({
                value: k.field,
                label: kindLabel(k.field),
                hint: k.files.toLocaleString(),
              }))}
            />
          )}
          {(sharing.length > 1 || chosenUses.length > 0) && (
            <MultiPick
              label="Used by"
              value={chosenUses.map(String)}
              onChange={(next) =>
                list.set({ used: next.length ? next.join(',') : undefined })
              }
              options={sharing.map((u) => ({
                value: String(u.records),
                label: `${u.records} record${u.records === 1 ? '' : 's'}`,
                hint: u.files.toLocaleString(),
              }))}
            />
          )}
          <Places
            summary={data?.summary ?? []}
            value={list.picks.place}
            onChange={(place) => list.set({ place: place || undefined })}
          />
          <OnServer
            counts={data?.server ?? []}
            value={list.picks.server}
            onChange={(server) => list.set({ server: server || undefined })}
          />
        </div>
        <PlacesBar places={data?.summary ?? []} />
        {followsServer && <Sending unsent={unsentOf(data)} />}
      </div>

      <SelectionBar
        selectedCount={picked.selected.size}
        pageCount={rows.length}
        total={total}
        allMatching={picked.allMatching}
        onSelectAllMatching={picked.selectAllMatching}
        actions={
          <>
            <MoveToDriveButton
              what={what}
              pick={target}
              onStarted={picked.clear}
            />
            {followsServer && (
              <>
                <Button
                  size="sm"
                  onClick={() => {
                    void downloadFiles(flow, target)
                    picked.clear()
                  }}
                >
                  Download to this computer
                </Button>
                <Button size="sm" onClick={() => setActing('free')}>
                  Free up space…
                </Button>
              </>
            )}
          </>
        }
      />

      <div aria-busy={isFetching}>
        <DataTable
          layout="auto"
          rows={rows}
          getRowId={(r) => r.sha256}
          isLoading={isLoading}
          error={error ? errorMessage(error) : undefined}
          emptyTitle="No files"
          emptyMessage={
            search
              ? 'No file or record matches the search.'
              : list.picks.place
                ? 'None here: pick another place to see more.'
                : 'None of these records holds a file.'
          }
          sort={
            list.sort
              ? { key: list.sort.field, direction: list.sort.dir }
              : undefined
          }
          onSortChange={list.toggleSort}
          selection={{
            ...picked.table,
            allLabel: 'Tick every file on this page',
            rowLabel: (id) =>
              `Tick ${rows.find((r) => r.sha256 === id)?.path ?? id}`,
          }}
          columns={[
            {
              key: 'name',
              header: 'File',
              sortable: true,
              render: (f: ListedFile) => (
                <FileCell file={f} kind={kindLabel(f.field)} />
              ),
            },
            {
              key: 'record',
              header: 'Record',
              sortable: true,
              render: (f) => <UsedBy file={f} />,
            },
            {
              key: 'size',
              header: 'Size',
              align: 'right',
              sortable: true,
              render: (f) => formatSize(f.size),
            },
            {
              key: 'place',
              header: 'Where',
              sortable: true,
              render: (f) => (
                <div className="flex flex-wrap items-center gap-x-2">
                  <PlaceStatus
                    place={f.place}
                    kind={f.place_kind}
                    reason={f.reason}
                    fix={f.fix}
                  />
                  {f.sent === false && f.volume && (
                    <span
                      className="text-xs text-fg-muted"
                      title="Other computers can’t open it until it is sent. It goes up in the background."
                    >
                      Not on the server yet
                    </span>
                  )}
                </div>
              ),
            },
          ]}
        />
        {total > list.size && (
          <Pagination
            page={list.page}
            pageSize={list.size}
            total={total}
            onPage={(page) => list.set({ page })}
            onPageSize={(size) => list.set({ size, page: 0 })}
          />
        )}
      </div>

      {acting === 'free' && (
        <FreeUpDialog
          what={what}
          count={() => free.mutateAsync({ pick: target, dryRun: true })}
          run={() =>
            free.mutateAsync({ pick: target, dryRun: false }).then((r) => {
              picked.clear()
              return r
            })
          }
          onClose={() => setActing(null)}
        />
      )}
    </div>
  )
}

function FileCell({ file, kind }: { file: ListedFile; kind: string }) {
  // Each record names the file by its own template: the first record's name
  // leads, and any other is shown beside it.
  const names = [
    ...new Set([file.filename, ...(file.uses ?? []).map((u) => u.filename)]),
  ]
  const otherNames = names.slice(1)
  const location = {
    volume: file.volume,
    state: file.state as never,
    available:
      file.place_kind === 'drive'
        ? true
        : file.place_kind === 'server'
          ? null
          : false,
    reason: file.reason,
    fix: file.fix,
  }
  return (
    <div className="min-w-0" title={file.path}>
      <FileLink
        file={{
          sha256: file.sha256,
          filename: file.filename,
          resolved_filename: file.filename,
          location,
        }}
        className="font-medium text-accent hover:underline"
      >
        {file.filename}
      </FileLink>
      <div className="text-xs text-fg-subtle">
        {kind}
        {otherNames.length > 0 && (
          <span title={names.join('\n')}>
            {' · also called '}
            {otherNames[0]}
            {otherNames.length > 1 ? ` and ${otherNames.length - 1} more` : ''}
          </span>
        )}
      </div>
    </div>
  )
}

/** The records that use a file: the first with the records above it, and
 * when there are more, a button opening every one of them (with those not
 * in this list too: moving the file moves it for them). */
function UsedBy({ file }: { file: ListedFile }) {
  const uses: FileUse[] = file.uses?.length
    ? file.uses
    : [
        {
          record_id: file.record_id,
          record_name: file.record_name,
          field: file.field,
          filename: file.filename,
          trail: [],
        },
      ]
  const [first] = uses
  const total = uses.length + (file.others ?? 0)
  return (
    <div className="min-w-0">
      <Link
        to={`/records/${first.record_id}`}
        className="text-accent hover:underline"
      >
        {first.trail.length > 0 && (
          <span className="text-fg-muted">{first.trail.join(' › ')} › </span>
        )}
        {first.record_name}
      </Link>
      {total > 1 && (
        <TriggerPopover
          label={`Records that use ${file.filename}`}
          trigger={({ toggle }) => (
            <Button variant="link" size="sm" onClick={toggle}>
              Used by {total} records
              {file.others ? ` (${file.others} not listed)` : ''}
            </Button>
          )}
        >
          <RecordsUsing sha256={file.sha256} here={uses} />
        </TriggerPopover>
      )}
    </div>
  )
}

/** Every live record that uses a file, each with the records above it and
 * its collection, those in this list first. */
function RecordsUsing({ sha256, here }: { sha256: string; here: FileUse[] }) {
  const { data, isLoading } = useFileInfo(sha256)
  const listed = new Set(here.map((u) => u.record_id))
  const all = data?.uses ?? []
  const rows = [
    ...all.filter((u) => listed.has(u.id)),
    ...all.filter((u) => !listed.has(u.id)),
  ]
  return (
    <div className="max-h-80 w-[28rem] max-w-[90vw] overflow-auto p-2 text-sm">
      {isLoading && <p className="p-2 text-fg-muted">Looking…</p>}
      <ul className="space-y-1">
        {rows.map((u) => (
          <li key={u.id} className="rounded px-2 py-1 hover:bg-canvas-inset">
            <Link
              to={`/records/${u.id}`}
              className="text-accent hover:underline"
            >
              {u.trail.length > 0 && (
                <span className="text-fg-muted">{u.trail.join(' › ')} › </span>
              )}
              {u.name}
            </Link>
            <div className="text-xs text-fg-subtle">
              {u.collection ?? ''}
              {listed.has(u.id) ? '' : ' · not in this list'}
            </div>
          </li>
        ))}
      </ul>
      {data && data.records > all.length && (
        <p className="p-2 text-xs text-fg-muted">
          and {(data.records - all.length).toLocaleString()} more
        </p>
      )}
      <div className="px-2">
        <DeletedKeepers count={data?.deleted_records} />
      </div>
    </div>
  )
}

/** Where the files are, each place a filter: click one to list only its
 * files, click it again (or All) to list them all. */
function Places({
  summary,
  value,
  onChange,
}: {
  summary: PlaceSummary[]
  value: string
  onChange: (place: string) => void
}) {
  if (summary.length === 0) return null
  const files = summary.reduce((n, p) => n + p.files, 0)
  const bytes = summary.reduce((n, p) => n + p.bytes, 0)
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Where">
      <Chip selected={!value} onClick={() => onChange('')}>
        All · {files.toLocaleString()} · {formatSize(bytes)}
      </Chip>
      {summary.map((p) => (
        <Chip
          key={`${p.kind}:${p.place}`}
          selected={value === p.place}
          onClick={() => onChange(value === p.place ? '' : p.place)}
          title={[p.reason, p.fix].filter(Boolean).join(' ') || undefined}
        >
          <StatusDot tone={PLACE_TONE[p.kind]} />
          {placeLabel(p)} · {p.files.toLocaleString()}
          {p.kind !== 'server' && p.kind !== 'missing'
            ? ` · ${formatSize(p.bytes)}`
            : ''}
        </Chip>
      ))}
    </div>
  )
}

const SERVER_LABEL: Record<ServerState, string> = {
  sent: 'On the server',
  unsent: 'Not on the server yet',
}

/** Whether the server has the files, each a filter like a place: click one
 * to list only those, click it again to list them all. Shown only while the
 * project follows a server. A file on no drive here isn't counted: nothing
 * here can send it, and the places say it is missing. */
function OnServer({
  counts,
  value,
  onChange,
}: {
  counts: NonNullable<FileListing['server']>
  value: string
  onChange: (state: string) => void
}) {
  if (counts.length === 0) return null
  return (
    <div
      className="flex flex-wrap gap-2"
      role="group"
      aria-label="On the server"
    >
      {counts.map((c) => (
        <Chip
          key={c.state}
          selected={value === c.state}
          onClick={() => onChange(value === c.state ? '' : c.state)}
        >
          <StatusDot tone={c.state === 'sent' ? 'ok' : 'attention'} />
          {SERVER_LABEL[c.state]} · {c.files.toLocaleString()}
        </Chip>
      ))}
    </div>
  )
}

function unsentOf(data: FileListing | undefined): number {
  return data?.server?.find((c) => c.state === 'unsent')?.files ?? 0
}

/** Files going up to the server right now, with how far along (the same
 * words and bar as the status bar), or, when some listed here aren't on the
 * server and nothing is going, how many and **Send now** (when any of this
 * project's can be read). Nothing otherwise. */
function Sending({ unsent }: { unsent: number }) {
  const { data } = useRemoteStatus()
  const sendNow = useSendFilesNow()
  const going = data?.files_progress
  if (going) {
    const text = describeSyncProgress(going)
    return (
      <div className="flex flex-wrap items-center gap-3 text-sm" role="status">
        <span className="font-medium">{text.title}</span>
        {text.fraction != null && (
          <ProgressBar fraction={text.fraction} label={text.title} />
        )}
        <span className="text-fg-muted">{text.count}</span>
      </div>
    )
  }
  if (unsent === 0) return null
  // Send now only does something for files on a drive that can be read.
  const canGo = (data?.files_waiting?.ready ?? 0) > 0
  return (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <span className="text-fg-muted">
        {unsent.toLocaleString()} file{unsent === 1 ? '' : 's'} here{' '}
        {unsent === 1 ? 'isn’t' : 'aren’t'} on the server yet
        {canGo ? '.' : ': the drive holding them can’t be read.'}
      </span>
      {canGo && (
        <Button
          size="sm"
          disabled={sendNow.isPending}
          onClick={() => sendNow.mutate()}
        >
          Send now
        </Button>
      )}
    </div>
  )
}
