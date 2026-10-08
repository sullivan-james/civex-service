import { useState } from 'react'
import { Link } from 'react-router'
import { logsApi, type LogLine } from '../../api/logs'
import { useLog, useLogSources } from '../../hooks/useLogs'
import { useListParams } from '../../hooks/useListParams'
import { errorMessage } from '../../lib/errors'
import { formatDateTime } from '../../utils/dates'
import {
  Badge,
  Button,
  CheckRow,
  DataTable,
  EmptyState,
  ListToolbar,
  type DataTableColumn,
} from '../ui'

const LEVELS = [
  { value: '', label: 'Any level' },
  { value: 'info', label: 'Info and above' },
  { value: 'warning', label: 'Warnings and errors' },
  { value: 'error', label: 'Errors' },
]

const SHOWN = 500

function sizeOf(bytes: number | null): string {
  if (bytes === null) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const TONE: Record<string, 'default' | 'attention' | 'danger'> = {
  warning: 'attention',
  error: 'danger',
  critical: 'danger',
}

function when(time: string | null): string {
  if (!time) return ''
  const parsed = new Date(time.replace(',', '.'))
  return Number.isNaN(parsed.getTime())
    ? time
    : formatDateTime(parsed.toISOString())
}

const COLUMNS: DataTableColumn<LogLine & { key: string }>[] = [
  {
    key: 'time',
    header: 'When',
    width: '170px',
    render: (l) => (
      <span className="whitespace-nowrap text-xs text-fg-muted">
        {when(l.time)}
      </span>
    ),
  },
  {
    key: 'level',
    header: 'Level',
    width: '90px',
    render: (l) =>
      l.level ? (
        <Badge variant={TONE[l.level] ?? 'default'}>{l.level}</Badge>
      ) : null,
  },
  {
    key: 'message',
    header: 'Message',
    render: (l) => {
      const extra = Object.entries(l.fields)
      return (
        <span className="font-mono text-xs break-all whitespace-pre-wrap">
          {l.message}
          {extra.length > 0 && (
            <span className="block text-fg-muted">
              {extra
                .map(
                  ([k, v]) =>
                    `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`,
                )
                .join('  ')}
            </span>
          )}
        </span>
      )
    },
  },
]

/** Every log civex keeps on this computer, in one place: this project's
 * server, the desktop app, its launcher, updates. Anything that says "see
 * the log" links here (`logHref`). */
export default function LogsSection() {
  const { data: sources, error: listError } = useLogSources()
  const list = useListParams('', ['log', 'level'])
  const [follow, setFollow] = useState(false)
  const [opened, setOpened] = useState<string | null>(null)
  const chosen =
    sources?.find((s) => s.id === list.picks.log) ?? sources?.[0] ?? null
  const { data, error, isFetching, refetch } = useLog(
    chosen?.id ?? null,
    {
      lines: SHOWN,
      level: list.picks.level || undefined,
      q: list.q || undefined,
    },
    follow,
  )
  // Newest first: what just went wrong is what people come for.
  const rows = [...(data?.lines ?? [])]
    .map((line, i) => ({ ...line, key: String(i) }))
    .reverse()
  const source = data?.source ?? chosen

  return (
    <div className="space-y-4">
      {listError && (
        <p role="alert" className="text-sm text-danger">
          {errorMessage(listError)}
        </p>
      )}
      <ListToolbar
        search={{
          value: list.q,
          label: 'Search this log',
          onChange: (q) => list.set({ q }),
        }}
        picks={[
          {
            label: 'Log',
            value: chosen?.id ?? '',
            options: (sources ?? []).map((s) => ({
              value: s.id,
              label: s.name,
            })),
            onChange: (log) => list.set({ log }),
          },
          {
            label: 'Any level',
            value: list.picks.level,
            options: LEVELS,
            onChange: (level) => list.set({ level }),
          },
        ]}
      />
      {source && (
        <div className="space-y-1 text-sm">
          <p className="text-fg-muted">{source.about}</p>
          <p className="font-mono text-xs break-all text-fg-muted">
            {source.path}
            {source.exists
              ? ` · ${sizeOf(source.size)} · last written ${when(source.modified)}`
              : ' · nothing written yet'}
          </p>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" disabled={isFetching} onClick={() => void refetch()}>
          {isFetching ? 'Reading…' : 'Refresh'}
        </Button>
        {source?.exists && (
          <>
            <Button size="sm" href={logsApi.downloadUrl(source.id)} download>
              Download
            </Button>
            <Button
              size="sm"
              onClick={() =>
                void logsApi
                  .open(source.id)
                  .then((r) =>
                    setOpened(
                      r.opened
                        ? null
                        : 'The folder can only be opened on the computer civex runs on.',
                    ),
                  )
              }
            >
              Open folder
            </Button>
          </>
        )}
        <CheckRow
          compact
          title="Follow"
          checked={follow}
          onChange={setFollow}
        />
      </div>
      {opened && <p className="text-xs text-fg-muted">{opened}</p>}
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {errorMessage(error)}
        </p>
      ) : source && !source.exists ? (
        <EmptyState title="Nothing written yet" />
      ) : (
        <DataTable
          dense
          layout="auto"
          columns={COLUMNS}
          rows={rows}
          getRowId={(l) => l.key}
          emptyTitle={
            list.q || list.picks.level ? 'No lines match' : 'This log is empty'
          }
        />
      )}
      <p className="text-xs text-fg-muted">
        Showing the latest {SHOWN} lines, newest first. A workflow run’s log is
        on the run’s own page, from{' '}
        <Link to="/runs" className="text-accent underline">
          Runs
        </Link>
        .
      </p>
    </div>
  )
}
