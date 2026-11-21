import { useState } from 'react'
import {
  queryBody,
  recordsApi,
  type QualityFinding,
  type QualityIssue,
} from '../../api/records'
import type { RecordQueryParams } from '../../api/query'
import type { Schema } from '../../api/schemas'
import { useQualityRecords, useRecordQuality } from '../../hooks/useRecords'
import { useListParams } from '../../hooks/useListParams'
import { useBulkSelection } from '../../hooks/useBulkSelection'
import {
  Button,
  DataTable,
  ErrorState,
  Pagination,
  Skeleton,
  Subheading,
  type DataTableColumn,
} from '../ui'
import { BulkEditDialog } from './BulkEditDialog'
import { errorMessage } from '../../lib/errors'
import { bulkEditableFields } from '../../utils/bulkEdit'
import type { FilterTreeWire } from '../../utils/filterTree'

/** Address names (beside the explorer's own): `chk.issue` and `chk.field`
 * (the line whose records are listed), `chk.page`, `chk.size`. */
const NS = 'chk.'
/** The most records a bulk edit of "all of them" takes from here: what one
 * request lists. */
const MOST_AT_ONCE = 1000

type Line = QualityIssue & { id: string }

/** What needs a look in the records the explorer lists (its kind, filters,
 * search and place): values their field's rules now refuse, required fields
 * left empty, shared unique keys, broken links and missing files, counted per
 * field. A line opens the records that have it, to open, or to tick and put
 * right with **Edit…**; an empty field's line lists them in the explorer. */
export function ChecksView({
  query,
  collection,
  listed,
  mayWrite,
  cannotWrite,
  onDrill,
}: {
  /** The explorer's own query: what it lists. */
  query: RecordQueryParams
  collection: string | undefined
  /** The kind listed: the fields **Edit…** offers. */
  listed: Schema
  mayWrite: boolean
  /** Why not, when `mayWrite` is false. */
  cannotWrite?: string
  /** List exactly some records in the explorer: a filter added to its own. */
  onDrill: (where: FilterTreeWire) => void
}) {
  const list = useListParams(NS, ['issue', 'field'], 25)
  const body = queryBody({ ...query, sort: undefined }, collection)
  const report = useRecordQuality(body)
  const kind = report.data?.kinds.find((k) => k.schema_name === listed.name)
  const labels = new Map(
    (report.data?.issues ?? []).map((i) => [i.name, i] as const),
  )
  const lines: Line[] = (kind?.issues ?? []).map((i) => ({
    ...i,
    id: `${i.issue}:${i.field}`,
  }))
  const open = lines.find(
    (l) => l.issue === list.picks.issue && l.field === list.picks.field,
  )

  if (report.error) return <ErrorState message={errorMessage(report.error)} />
  if (!report.data) return <Skeleton className="h-24" />

  const total = kind?.records ?? 0
  const flagged = kind?.records_with_issues ?? 0
  const columns: DataTableColumn<Line>[] = [
    {
      key: 'issue',
      header: 'What',
      render: (l) => (
        <span title={labels.get(l.issue)?.description}>
          {labels.get(l.issue)?.label ?? l.issue}
        </span>
      ),
    },
    { key: 'field', header: 'Field', render: (l) => l.field_label },
    {
      key: 'count',
      header: 'Records',
      align: 'right',
      width: '7rem',
      render: (l) => l.count.toLocaleString(),
    },
    {
      key: 'example',
      header: 'For example',
      render: (l) =>
        l.examples[0] ? (
          <span className="text-fg-muted">
            {l.examples[0].record_name ?? l.examples[0].record_id.slice(0, 8)}:{' '}
            {l.examples[0].message}
          </span>
        ) : null,
    },
  ]

  return (
    <div className={`space-y-4 ${report.isFetching ? 'opacity-70' : ''}`}>
      <p className="text-sm" aria-live="polite">
        {flagged === 0 ? (
          'No problems'
        ) : (
          <>
            <span className="font-medium">{flagged.toLocaleString()}</span> of{' '}
            {total.toLocaleString()} records
          </>
        )}
      </p>

      {lines.length > 0 && (
        <DataTable
          columns={columns}
          rows={lines}
          getRowId={(l) => l.id}
          onRowClick={(l) =>
            open?.id === l.id
              ? list.set({ issue: '', field: '' })
              : list.set({ issue: l.issue, field: l.field })
          }
          rowClassName={(l) => (open?.id === l.id ? 'bg-accent-subtle' : '')}
        />
      )}

      {open && (
        <IssueRecords
          key={open.id}
          line={open}
          label={labels.get(open.issue)?.label ?? open.issue}
          request={{
            ...body,
            issue: open.issue,
            field: open.field,
            kind: listed.name,
          }}
          page={list.page}
          size={list.size}
          onPage={(page) => list.set({ page })}
          onPageSize={(size) => list.set({ size })}
          listed={listed}
          mayWrite={mayWrite}
          cannotWrite={cannotWrite}
          onDrill={onDrill}
          onClose={() => list.set({ issue: '', field: '' })}
        />
      )}
    </div>
  )
}

function IssueRecords({
  line,
  label,
  request,
  page,
  size,
  onPage,
  onPageSize,
  listed,
  mayWrite,
  cannotWrite,
  onDrill,
  onClose,
}: {
  line: QualityIssue
  label: string
  request: Parameters<typeof recordsApi.qualityRecords>[0]
  page: number
  size: number
  onPage: (page: number) => void
  onPageSize: (size: number) => void
  listed: Schema
  mayWrite: boolean
  cannotWrite?: string
  onDrill: (where: FilterTreeWire) => void
  onClose: () => void
}) {
  const found = useQualityRecords({
    ...request,
    limit: size,
    offset: page * size,
  })
  const items = found.data?.items ?? []
  const total = found.data?.total ?? 0
  const picked = useBulkSelection(
    items.map((f) => f.record_id),
    JSON.stringify([line.issue, line.field, page, size]),
  )
  const [editing, setEditing] = useState<string[] | null>(null)
  const [gathering, setGathering] = useState(false)
  const [gatherError, setGatherError] = useState<string | null>(null)
  const count = picked.count(total)
  const canEdit = bulkEditableFields(listed).length > 0

  async function edit() {
    if (!picked.allMatching) {
      setEditing([...picked.selected])
      return
    }
    setGathering(true)
    setGatherError(null)
    try {
      const all = await recordsApi.qualityRecords({
        ...request,
        limit: MOST_AT_ONCE,
        offset: 0,
      })
      setEditing(all.items.map((f) => f.record_id))
    } catch (e) {
      setGatherError(errorMessage(e))
    } finally {
      setGathering(false)
    }
  }

  const columns: DataTableColumn<QualityFinding>[] = [
    {
      key: 'record',
      header: 'Record',
      render: (f) => f.record_name ?? f.record_id.slice(0, 8),
    },
    {
      key: 'message',
      header: 'What is wrong',
      render: (f) => <span className="text-fg-muted">{f.message}</span>,
    },
  ]

  return (
    <section
      aria-label={`${label}: ${line.field_label}`}
      className="space-y-2 rounded-md border border-border p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Subheading>
          {label}: {line.field_label}
        </Subheading>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {line.filter && (
            <Button size="sm" onClick={() => onDrill(line.filter!)}>
              Show in the list
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>

      {(picked.selected.size > 0 || picked.allMatching) && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span>
            {count.toLocaleString()} ticked
            {!picked.allMatching && total > items.length && (
              <>
                {' · '}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={picked.selectAllMatching}
                  disabled={total > MOST_AT_ONCE}
                  title={
                    total > MOST_AT_ONCE
                      ? `At most ${MOST_AT_ONCE.toLocaleString()} at once`
                      : undefined
                  }
                >
                  Tick all {total.toLocaleString()}
                </Button>
              </>
            )}
          </span>
          {canEdit && (
            <Button
              size="sm"
              disabled={!mayWrite || gathering}
              title={mayWrite ? undefined : cannotWrite}
              onClick={edit}
            >
              Edit…
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={picked.clear}>
            Clear
          </Button>
        </div>
      )}
      {gatherError && <ErrorState message={gatherError} />}

      <DataTable
        columns={columns}
        rows={items}
        getRowId={(f) => f.record_id}
        rowHref={(f) => `/records/${f.record_id}`}
        selection={picked.table}
        isLoading={found.isLoading}
        error={found.error ? errorMessage(found.error) : undefined}
        emptyTitle="None left"
        emptyMessage="No records have this any more."
      />
      <Pagination
        page={page}
        pageSize={size}
        total={total}
        onPage={onPage}
        onPageSize={onPageSize}
      />

      {editing && (
        <BulkEditDialog
          selection={{ ids: editing }}
          count={editing.length}
          listed={listed}
          onClose={() => setEditing(null)}
          onDone={picked.clear}
        />
      )}
    </section>
  )
}
