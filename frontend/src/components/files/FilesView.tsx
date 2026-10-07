import { useState } from 'react'
import { Link } from 'react-router'
import type {
  FilePick,
  FileUse,
  FileSelection,
  ListedFile,
  PlaceSummary,
} from '../../api/fileAccess'
import { useListParams } from '../../hooks/useListParams'
import { useFollowsServer } from '../../hooks/useRemote'
import { useSchemas } from '../../hooks/useSchemas'
import { PROJECT, useDriveChoice } from '../../hooks/useDriveChoice'
import { useVolumes } from '../../hooks/useStore'
import { useQueryClient } from '@tanstack/react-query'
import { useFileListing, useFreeUpFiles } from '../../hooks/useFileListing'
import { useFileInfo } from '../../hooks/useFiles'
import { useQuery } from '@tanstack/react-query'
import { fileAccessApi } from '../../api/fileAccess'
import { errorMessage } from '../../lib/errors'
import { displayLabel } from '../../utils/naming'
import { placeLabel } from '../../utils/places'
import { formatSize } from '../../utils/storage'
import { FileLink } from '../records/FileLocation'
import { SelectionBar } from '../explorer/SelectionBar'
import { useBulkSelection } from '../../hooks/useBulkSelection'
import { FreeUpDialog } from '../settings/storage/ComputerFiles'
import {
  Button,
  CheckRow,
  Chip,
  DataTable,
  MultiPick,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Pagination,
  TriggerPopover,
  useToast,
} from '../ui'
import { DrivePicker } from './DrivePicker'
import { downloadFiles, moveFiles, type FlowContext } from './fileFlows'
import { ToDownloadNotice } from './ToDownloadNotice'

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
  const list = useListParams(NS, ['place', 'kind', 'used'], 50)
  const { data: schemas = [] } = useSchemas()
  const followsServer = useFollowsServer()
  const [acting, setActing] = useState<'move' | 'free' | null>(null)
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
        </div>
        <PlacesBar summary={data?.summary ?? []} />
      </div>

      <SelectionBar
        selectedCount={picked.selected.size}
        pageCount={rows.length}
        total={total}
        allMatching={picked.allMatching}
        onSelectAllMatching={picked.selectAllMatching}
        actions={
          <>
            <Button size="sm" onClick={() => setActing('move')}>
              Move to drive…
            </Button>
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
                <span
                  className={
                    f.place_kind === 'drive'
                      ? 'text-fg'
                      : f.place_kind === 'server'
                        ? 'text-fg-muted'
                        : 'text-attention'
                  }
                  title={f.reason ? `${f.reason} ${f.fix}`.trim() : undefined}
                >
                  {placeLabel({ place: f.place, kind: f.place_kind })}
                </span>
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

      {acting === 'move' && (
        <MoveDialog
          what={what}
          pick={target}
          summary={data?.summary ?? []}
          onClose={() => setActing(null)}
          onMove={(volume, includeShared) => {
            void moveFiles(flow, target, volume, includeShared)
            picked.clear()
            setActing(null)
          }}
        />
      )}
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
        >
          {placeLabel(p)} · {p.files.toLocaleString()}
          {p.kind !== 'server' && p.kind !== 'missing'
            ? ` · ${formatSize(p.bytes)}`
            : ''}
        </Chip>
      ))}
    </div>
  )
}

/** The same places as one bar, sized by bytes, with why a drive can't be
 * read beneath it. */
function PlacesBar({ summary }: { summary: PlaceSummary[] }) {
  if (summary.length === 0) return null
  const bytes = summary.reduce((n, p) => n + p.bytes, 0)
  const unreachable = summary.filter((p) => p.kind === 'unreachable')
  return (
    <>
      <div
        role="img"
        aria-label={summary
          .map((p) => `${placeLabel(p)}: ${p.files} files`)
          .join(', ')}
        className="flex h-1.5 overflow-hidden rounded-full bg-canvas-inset"
      >
        {summary.map((p) => (
          <div
            key={`${p.kind}:${p.place}`}
            className={
              p.kind === 'drive'
                ? 'bg-accent'
                : p.kind === 'server'
                  ? 'bg-border'
                  : 'bg-attention'
            }
            style={{
              width: `${(Math.max(p.bytes, 1) / Math.max(bytes, 1)) * 100}%`,
            }}
          />
        ))}
      </div>
      {unreachable.map((p) => (
        <p key={p.place} role="status" className="text-xs text-attention">
          {p.place}: {p.reason} {p.fix}
        </p>
      ))}
    </>
  )
}

/** Move the picked files onto one drive: the drive and whether they fit
 * (the shared drive-and-free-space rule), what has to be downloaded first and
 * what can't move; the move itself then runs as a job in the status bar. */
function MoveDialog({
  what,
  pick,
  summary,
  onClose,
  onMove,
}: {
  what: string
  pick: FilePick
  summary: PlaceSummary[]
  onClose: () => void
  onMove: (volume: string, includeShared: boolean) => void
}) {
  // Suggest somewhere else: the drive the files are on (the place being
  // looked at, else the one holding most) is where they would move from.
  const from =
    pick.place ??
    [...summary]
      .filter((p) => p.kind === 'drive')
      .sort((a, b) => b.files - a.files)[0]?.place
  const { data: volumes = [] } = useVolumes()
  const elsewhere = volumes.find(
    (v) => v.available && v.state === 'online' && v.name !== from,
  )?.name
  const [chosen, setChosen] = useState<string | null>(null)
  const [includeShared, setIncludeShared] = useState(false)
  const drive = useDriveChoice({
    holding: elsewhere,
    need: 0,
    allowProject: false,
    chosen,
  })
  // What it would do, asked of the server for the drive chosen: the same
  // rule the move itself follows.
  const { data: preview } = useQuery({
    queryKey: ['move-plan', pick, drive.target, includeShared],
    queryFn: () => fileAccessApi.planMove(pick, drive.target, includeShared),
    enabled: !!drive.target && drive.target !== PROJECT,
  })
  const plan = preview?.plan
  const stuck = summary.filter(
    (p) => p.kind === 'unreachable' || p.kind === 'missing',
  )
  return (
    <Modal onClose={onClose}>
      <ModalHeader onClose={onClose}>Move {what} to a drive</ModalHeader>
      <ModalBody className="space-y-3 text-sm">
        <DrivePicker
          label="Move them onto"
          value={drive.target}
          targets={drive.targets}
          allowProject={false}
          need={plan?.bytes ?? 0}
          free={drive.free}
          tooBig={drive.free != null && (plan?.bytes ?? 0) > drive.free}
          onChange={setChosen}
        />
        {plan && (
          <p>
            {plan.files === 0 && plan.from_server === 0
              ? 'Nothing to move: they are there already.'
              : `Moves ${plan.files.toLocaleString()} file${plan.files === 1 ? '' : 's'} (${formatSize(plan.bytes)}).`}
            {plan.already_there > 0 &&
              ` ${plan.already_there.toLocaleString()} are there already.`}
          </p>
        )}
        {plan && plan.from_server > 0 && (
          <ToDownloadNotice toFetch={{ files: plan.from_server, bytes: 0 }} />
        )}
        {plan && (plan.shared_left > 0 || includeShared) && (
          <CheckRow
            checked={includeShared}
            onChange={setIncludeShared}
            title={
              includeShared
                ? 'Moving the files other records also use too'
                : `Also move ${plan.shared_left.toLocaleString()} file${plan.shared_left === 1 ? '' : 's'} other records use (${formatSize(plan.shared_bytes)})`
            }
            description="Some of these files are also used by records you didn't pick. They stay where they are unless you tick this; ticked, they move for those records too."
          />
        )}
        {stuck.length > 0 && (
          <p className="text-attention">
            Left where they are:{' '}
            {stuck
              .map((p) => `${p.files} ${placeLabel(p).toLowerCase()}`)
              .join(', ')}
            .
          </p>
        )}
      </ModalBody>
      <ModalFooter>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="primary"
          disabled={
            !drive.target ||
            drive.target === PROJECT ||
            !plan ||
            (plan.files === 0 && plan.from_server === 0)
          }
          onClick={() => onMove(drive.target, includeShared)}
        >
          Move
        </Button>
      </ModalFooter>
    </Modal>
  )
}
