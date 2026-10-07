import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import type { FilePick, ListedFile, PlaceSummary } from '../../api/fileAccess'
import type { FilterTreeWire } from '../../utils/filterTree'
import { useListParams } from '../../hooks/useListParams'
import { useFollowsServer } from '../../hooks/useRemote'
import { useSchemas } from '../../hooks/useSchemas'
import { PROJECT, useDriveChoice } from '../../hooks/useDriveChoice'
import { useQueryClient } from '@tanstack/react-query'
import { useFileListing, useFreeUpFiles } from '../../hooks/useFileListing'
import { errorMessage } from '../../lib/errors'
import { filterableFields } from '../../utils/hierarchy'
import { placeLabel } from '../../utils/places'
import { formatSize } from '../../utils/storage'
import { FilterControls } from '../explorer/FilterControls'
import { FileLink } from '../records/FileLocation'
import { FreeUpDialog } from '../settings/storage/ComputerFiles'
import {
  Button,
  Chip,
  DataTable,
  Input,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Pagination,
  Select,
  useToast,
} from '../ui'
import { DrivePicker } from './DrivePicker'
import { downloadFiles, moveFiles, type FlowContext } from './fileFlows'
import { ToDownloadNotice } from './ToDownloadNotice'

const NS = 'files.'

/** The files of a collection, or of a record and everything beneath it: where
 * each one is, picked out by kind of record (with the explorer's own filter),
 * place and name, and acted on: moved onto a drive, downloaded from the
 * server, or removed from this computer to free space. Everything is in the
 * address, so a view of "the 2024 recordings still on the field SSD" is a
 * link. What is listed is exactly what an action takes (the server picks both
 * by the same rule). */
export function FilesTab({
  scope,
}: {
  /** A collection (by name), and/or a record whose files and its
   * descendants' are taken. */
  scope: { collection?: string; within?: string }
}) {
  const list = useListParams(NS, ['place', 'kind'], 50)
  const [sp, setSp] = useSearchParams()
  const { data: schemas = [] } = useSchemas()
  const followsServer = useFollowsServer()
  const [ticked, setTicked] = useState<Set<string>>(new Set())
  const [acting, setActing] = useState<'move' | 'free' | null>(null)
  const toast = useToast()

  const kind = list.picks.kind
  const kindSchema = schemas.find((s) => s.name === kind)
  const filter = useMemo<FilterTreeWire | null>(() => {
    const raw = sp.get(`${NS}filter`)
    try {
      return raw ? (JSON.parse(raw) as FilterTreeWire) : null
    } catch {
      return null
    }
  }, [sp])
  const kinds = schemas.filter((s) =>
    s.fields.some((f) => f.type === 'file' || f.type === 'file_list'),
  )
  const fields = useMemo(
    () => (kindSchema ? filterableFields(kindSchema, schemas) : []),
    [kindSchema, schemas],
  )

  const pick: FilePick = {
    ...scope,
    schema_name: kind || undefined,
    filter: kind && filter ? filter : undefined,
    place: list.picks.place || undefined,
    name: list.q || undefined,
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
  const shas = [
    ...new Set(rows.filter((r) => ticked.has(r.path)).map((r) => r.sha256)),
  ]
  // Ticked rows, else everything that matches.
  const target: FilePick = shas.length ? { ...pick, shas } : pick
  const what = shas.length
    ? `${shas.length.toLocaleString()} ticked file${shas.length === 1 ? '' : 's'}`
    : `all ${(data?.total ?? 0).toLocaleString()} matching`
  const onServer = data?.summary.find((p) => p.kind === 'server')?.files ?? 0

  const free = useFreeUpFiles()
  const qc = useQueryClient()
  // Moving and downloading run as file jobs: progress in the status bar, and
  // they carry on if the page is left.
  const flow: FlowContext = { toast, qc, problem: () => undefined }

  function setFilter(wire: FilterTreeWire | null) {
    setSp(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.delete(`${NS}page`)
        if (wire) next.set(`${NS}filter`, JSON.stringify(wire))
        else next.delete(`${NS}filter`)
        return next
      },
      { replace: true },
    )
  }

  return (
    <div className="space-y-4">
      <Places
        summary={data?.summary ?? []}
        value={list.picks.place}
        onChange={(place) => {
          setTicked(new Set())
          list.set({ place: place || undefined })
        }}
      />

      <div className="flex flex-wrap items-center gap-3">
        <Input
          aria-label="Find files by name"
          placeholder="File or record name"
          value={list.q}
          onChange={(e) => list.set({ q: e.target.value || undefined })}
          className="w-64"
        />
        <Select
          size="sm"
          aria-label="Records of kind"
          value={kind}
          onChange={(e) => {
            setTicked(new Set())
            setSp(
              (prev) => {
                const next = new URLSearchParams(prev)
                next.delete(`${NS}page`)
                next.delete(`${NS}filter`)
                if (e.target.value) next.set(`${NS}kind`, e.target.value)
                else next.delete(`${NS}kind`)
                return next
              },
              { replace: true },
            )
          }}
        >
          <option value="">Every kind of record</option>
          {kinds.map((s) => (
            <option key={s.name} value={s.name}>
              {s.label ?? s.name}
            </option>
          ))}
        </Select>
      </div>
      {kindSchema && (
        <FilterControls
          wire={filter}
          fields={fields}
          listedSchema={kindSchema.name}
          onChange={setFilter}
        />
      )}

      <div
        role="region"
        aria-label="Act on files"
        className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-canvas-subtle px-3 py-2 text-sm"
      >
        <span className="text-fg-muted">{what}:</span>
        <Button
          size="sm"
          disabled={!data?.total}
          onClick={() => setActing('move')}
        >
          Move to drive…
        </Button>
        {followsServer && (
          <>
            <Button
              size="sm"
              disabled={!onServer}
              onClick={() => void downloadFiles(flow, target)}
            >
              Download to this computer
            </Button>
            <Button
              size="sm"
              disabled={!data?.total}
              onClick={() => setActing('free')}
            >
              Free up space…
            </Button>
          </>
        )}
        {shas.length > 0 && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setTicked(new Set())}
          >
            Clear ticks
          </Button>
        )}
      </div>

      <DataTable
        dense
        rows={rows}
        getRowId={(r) => r.path}
        isLoading={isLoading}
        error={error ? errorMessage(error) : undefined}
        emptyTitle="No files"
        emptyMessage={
          list.picks.place || list.q || filter
            ? 'None match: clear a filter to see more.'
            : 'No record here holds a file.'
        }
        sort={
          list.sort
            ? { key: list.sort.field, direction: list.sort.dir }
            : undefined
        }
        onSortChange={list.toggleSort}
        className={isFetching ? 'opacity-80' : undefined}
        selection={{
          selected: ticked,
          onToggle: (id) =>
            setTicked((prev) => {
              const next = new Set(prev)
              if (next.has(id)) next.delete(id)
              else next.add(id)
              return next
            }),
          onSetMany: (ids, on) =>
            setTicked((prev) => {
              const next = new Set(prev)
              for (const id of ids) {
                if (on) next.add(id)
                else next.delete(id)
              }
              return next
            }),
          onToggleAll: () =>
            setTicked((prev) =>
              rows.every((r) => prev.has(r.path))
                ? new Set()
                : new Set(rows.map((r) => r.path)),
            ),
          allLabel: 'Tick every file on this page',
          rowLabel: (id) => `Tick ${id}`,
        }}
        columns={[
          {
            key: 'name',
            header: 'File',
            sortable: true,
            render: (f: ListedFile) => <FileCell file={f} />,
          },
          {
            key: 'record',
            header: 'Record',
            sortable: true,
            render: (f) => (
              <Link
                to={`/records/${f.record_id}`}
                className="text-accent hover:underline"
              >
                {f.record_name}
              </Link>
            ),
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
      {data && data.total > list.size && (
        <Pagination
          page={list.page}
          pageSize={list.size}
          total={data.total}
          onPage={(page) => list.set({ page })}
          onPageSize={(size) => list.set({ size, page: 0 })}
        />
      )}

      {acting === 'move' && (
        <MoveDialog
          what={what}
          pick={target}
          summary={data?.summary ?? []}
          onClose={() => setActing(null)}
          onMove={(volume) => {
            void moveFiles(flow, target, volume)
            setTicked(new Set())
            setActing(null)
          }}
        />
      )}
      {acting === 'free' && (
        <FreeUpDialog
          what={
            shas.length
              ? what
              : `these ${(data?.total ?? 0).toLocaleString()} files`
          }
          count={() => free.mutateAsync({ pick: target, dryRun: true })}
          run={() =>
            free.mutateAsync({ pick: target, dryRun: false }).then((r) => {
              setTicked(new Set())
              return r
            })
          }
          onClose={() => setActing(null)}
        />
      )}
    </div>
  )
}

function FileCell({ file }: { file: ListedFile }) {
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
    <div className="min-w-0">
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
      <div className="truncate text-xs text-fg-subtle" title={file.path}>
        {file.field} · {file.path}
      </div>
    </div>
  )
}

/** Where all of the files are, each place a filter: click one to list only
 * its files, click it again (or All) to list them all. */
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
  const unreachable = summary.filter((p) => p.kind === 'unreachable')
  return (
    <div className="space-y-2">
      <div
        role="img"
        aria-label={summary
          .map((p) => `${placeLabel(p)}: ${p.files} files`)
          .join(', ')}
        className="flex h-2 overflow-hidden rounded-full bg-canvas-inset"
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
      {unreachable.map((p) => (
        <p key={p.place} role="status" className="text-xs text-attention">
          {p.place}: {p.reason} {p.fix}
        </p>
      ))}
    </div>
  )
}

/** Move the picked files onto one drive: the drive and whether they fit
 * (the shared drive-and-free-space rule), what has to be downloaded first and
 * what can't move; the move itself then runs as a job in the status bar. */
function MoveDialog({
  what,
  summary,
  onClose,
  onMove,
}: {
  what: string
  pick: FilePick
  summary: PlaceSummary[]
  onClose: () => void
  onMove: (volume: string) => void
}) {
  const holding = summary.find((p) => p.kind === 'drive')?.place
  const total = summary.reduce((n, p) => n + p.bytes, 0)
  const [chosen, setChosen] = useState<string | null>(null)
  const drive = useDriveChoice({
    holding,
    need: total,
    allowProject: false,
    chosen,
  })
  const stuck = summary.filter(
    (p) => p.kind === 'unreachable' || p.kind === 'missing',
  )
  const server = summary.find((p) => p.kind === 'server')
  return (
    <Modal onClose={onClose}>
      <ModalHeader onClose={onClose}>Move {what} to a drive</ModalHeader>
      <ModalBody className="space-y-3 text-sm">
        <p>
          Only these files move; the rest of their collections stay where they
          are. Files already on the drive are left as they are.
        </p>
        <ToDownloadNotice toFetch={server} />
        {stuck.length > 0 && (
          <p className="text-attention">
            Left where they are:{' '}
            {stuck
              .map((p) => `${p.files} ${placeLabel(p).toLowerCase()}`)
              .join(', ')}
            .
          </p>
        )}
        <DrivePicker
          label="Move them onto"
          value={drive.target}
          targets={drive.targets}
          allowProject={false}
          need={total}
          free={drive.free}
          tooBig={drive.tooBig}
          onChange={setChosen}
        />
      </ModalBody>
      <ModalFooter>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="primary"
          disabled={!drive.target || drive.target === PROJECT}
          onClick={() => onMove(drive.target)}
        >
          Move
        </Button>
      </ModalFooter>
    </Modal>
  )
}
