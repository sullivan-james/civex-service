import { useMemo, useState } from 'react'
import { recordsApi, queryBody, type SummaryRow } from '../../api/records'
import type { RecordQueryParams } from '../../api/query'
import { useRecordSummary } from '../../hooks/useRecords'
import { useFieldTypes } from '../../hooks/useFieldTypes'
import { useListParams } from '../../hooks/useListParams'
import {
  Button,
  Chip,
  DataTable,
  ErrorState,
  Field,
  InfoTip,
  Input,
  Menu,
  Select,
  type DataTableColumn,
  type MenuEntry,
} from '../ui'
import { ChevronDown, Download, Plus } from '../ui/icons'
import { saveBlob } from '../files/fileFlows'
import { TABLE_FORMATS } from '../../utils/tableFormats'
import { errorMessage } from '../../lib/errors'
import { displayLabel } from '../../utils/naming'
import type { FilterableField } from '../../utils/hierarchy'
import type { FilterTreeWire } from '../../utils/filterTree'
import {
  compareSummaryCells,
  fieldKey,
  formatSummaryValue,
  splitGroupKey,
  splitKeys,
  summaryFields,
} from '../../utils/summary'

/** Address names (beside the explorer's own): `sum.by`, `sum.m`, `sum.sort`. */
const NS = 'sum.'
const PERIOD_NAMES: Record<string, string> = {
  year: 'By year',
  month: 'By month',
  week: 'By week',
  day: 'By day',
}
const TOTAL_ID = '__total'

type Row = { id: string; row: SummaryRow | null; cells: unknown[] }

/** The records the explorer lists, summarised: grouped by fields of their
 * kind (or of a kind above it), with counts, averages and the like for each
 * group and a total. The choices are in the address, so a summary is a
 * link. Clicking a group lists its records. */
export function SummaryView({
  query,
  collection,
  fields,
  onDrill,
}: {
  /** The explorer's own query: what it lists. */
  query: RecordQueryParams
  collection: string | undefined
  /** The listed kind's fields and its relatives' (`filterableFields`). */
  fields: FilterableField[]
  /** List the records of a group: its condition, added to the filter. */
  onDrill: (where: FilterTreeWire) => void
}) {
  const list = useListParams(NS, ['by', 'm'])
  const by = splitKeys(list.picks.by)
  const chosenMeasures = splitKeys(list.picks.m)
  const measures = chosenMeasures.length ? chosenMeasures : ['count']
  const types = useFieldTypes()
  const usable = useMemo(
    () => summaryFields(fields, types?.types ?? []),
    [fields, types],
  )
  const measureNames = new Map(
    (types?.summary_measures ?? []).map((m) => [m.key, m]),
  )
  const byKey = new Map(usable.map((u) => [fieldKey(u.field), u]))
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState<string | null>(null)

  const body = query.schema
    ? {
        ...queryBody({ ...query, sort: undefined }, collection),
        group_by: by,
        measures,
      }
    : null
  const { data, isLoading, isFetching, error } = useRecordSummary(body)

  const setBy = (next: string[]) => list.set({ by: next.join(',') })
  const setMeasures = (next: string[]) =>
    list.set({
      m: next.length === 1 && next[0] === 'count' ? '' : next.join(','),
    })

  function labelOf(f: FilterableField) {
    const own = displayLabel(f.name, f.label)
    return f.relation === 'self' ? own : `${f.sourceSchemaName} › ${own}`
  }

  // --- what can be added
  const groupItems: MenuEntry[] = []
  let lastKind = ''
  for (const { field, type } of usable) {
    if (!type.grouping) continue
    const key = fieldKey(field)
    if (by.some((b) => splitGroupKey(b).field === key)) continue
    if (field.sourceSchemaName !== lastKind) {
      lastKind = field.sourceSchemaName
      groupItems.push({ heading: field.sourceSchemaName })
    }
    groupItems.push({
      label: displayLabel(field.name, field.label),
      hint: type.grouping === 'each' ? 'A group for each item' : undefined,
      onClick: () =>
        setBy([
          ...by,
          type.grouping === 'bucket' && type.buckets.includes('month')
            ? `${key}:month`
            : key,
        ]),
    })
  }
  const measureItems: MenuEntry[] = []
  if (!measures.includes('count'))
    measureItems.push({
      label: measureNames.get('count')?.label ?? 'Records',
      hint: measureNames.get('count')?.help,
      onClick: () => setMeasures([...measures, 'count']),
    })
  for (const { field, type } of usable) {
    const key = fieldKey(field)
    const open = type.measures.filter((m) => !measures.includes(`${m}:${key}`))
    if (open.length === 0) continue
    measureItems.push({ heading: labelOf(field) })
    for (const m of open)
      measureItems.push({
        label: measureNames.get(m)?.label ?? m,
        onClick: () => setMeasures([...measures, `${m}:${key}`]),
      })
  }

  // --- the table
  const groupCols = data?.group_columns ?? []
  const measureCols = data?.measure_columns ?? []
  const rows: Row[] = (data?.rows ?? []).map((row, i) => ({
    id: String(i),
    row,
    cells: [...row.groups.map((g) => g.value), ...row.values],
  }))
  const sortIndex = list.sort
    ? [...groupCols, ...measureCols].findIndex(
        (c) => c.key === list.sort!.field,
      )
    : -1
  if (sortIndex >= 0) {
    const dir = list.sort!.dir === 'desc' ? -1 : 1
    rows.sort(
      (a, b) =>
        dir * compareSummaryCells(a.cells[sortIndex], b.cells[sortIndex]),
    )
  }
  if (data && groupCols.length > 0)
    rows.push({
      id: TOTAL_ID,
      row: null,
      cells: [...groupCols.map(() => null), ...data.total],
    })
  if (data && groupCols.length === 0)
    rows.push({ id: TOTAL_ID, row: null, cells: data.total })

  const columns: DataTableColumn<Row>[] = [
    ...groupCols.map<DataTableColumn<Row>>((c, i) => ({
      key: c.key,
      header: c.label,
      sortable: true,
      render: (r) =>
        r.row === null ? (
          i === 0 ? (
            <span className="font-semibold">Total</span>
          ) : null
        ) : (
          <span
            className={
              r.row.groups[i].value === null || r.row.groups[i].precision
                ? 'italic text-fg-muted'
                : undefined
            }
          >
            {r.row.groups[i].label}
          </span>
        ),
    })),
    ...measureCols.map<DataTableColumn<Row>>((c, i) => ({
      key: c.key,
      header: c.unit ? `${c.label} (${c.unit})` : c.label,
      headerTitle: measureNames.get(c.measure)?.help,
      align: 'right',
      sortable: true,
      render: (r) => (
        <span className={r.row === null ? 'font-semibold' : undefined}>
          {formatSummaryValue(r.cells[groupCols.length + i])}
        </span>
      ),
    })),
  ]

  async function download(format: string) {
    if (!body) return
    setDownloading(true)
    setDownloadError(null)
    try {
      const got = await recordsApi.summaryFile(body, format)
      saveBlob(got.blob, got.filename ?? `summary.${format}`)
    } catch (e) {
      setDownloadError(errorMessage(e))
    } finally {
      setDownloading(false)
    }
  }

  if (!query.schema)
    return (
      <p className="text-sm text-fg-muted">
        Choose a kind of record to summarise.
      </p>
    )

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-fg-muted">Group by</span>
        {by.map((key) => {
          const { field, how } = splitGroupKey(key)
          const u = byKey.get(field)
          const name = u ? labelOf(u.field) : field
          const replace = (next: string) =>
            setBy(by.map((b) => (b === key ? next : b)))
          return (
            <span key={key} className="inline-flex items-center gap-1">
              <Chip
                onRemove={() => setBy(by.filter((b) => b !== key))}
                removeLabel={`Stop grouping by ${name}`}
              >
                {name}
              </Chip>
              {u?.type.grouping === 'bucket' && (
                <Select
                  size="sm"
                  aria-label={`How to group ${name}`}
                  value={how}
                  onChange={(e) =>
                    replace(
                      e.target.value ? `${field}:${e.target.value}` : field,
                    )
                  }
                >
                  <option value="">Each value</option>
                  {u.type.buckets.map((b) => (
                    <option key={b} value={b}>
                      {PERIOD_NAMES[b] ?? b}
                    </option>
                  ))}
                </Select>
              )}
              {u?.type.grouping === 'bin' && (
                <Field label={`Range width for ${name}`} hideLabel>
                  <Input
                    size="sm"
                    type="number"
                    min={0}
                    step="any"
                    className="w-28"
                    placeholder="Each value"
                    title="Group into ranges this wide (leave empty for each value)"
                    defaultValue={how}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') e.currentTarget.blur()
                    }}
                    onBlur={(e) => {
                      const w = Number(e.target.value)
                      const next =
                        e.target.value && w > 0 ? `${field}:${w}` : field
                      if (next !== key) replace(next)
                    }}
                  />
                </Field>
              )}
            </span>
          )
        })}
        {by.length < 3 && groupItems.length > 0 && (
          <Menu
            align="left"
            wide
            items={groupItems}
            trigger={({ open, toggle }) => (
              <Button
                size="sm"
                aria-haspopup="menu"
                aria-expanded={open}
                onClick={toggle}
              >
                <Plus size={14} /> {by.length ? 'And by…' : 'Group by…'}
                <ChevronDown size={14} />
              </Button>
            )}
          />
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-fg-muted">Show</span>
        {measures.map((key) => {
          const col = measureCols.find((c) => c.key === key)
          return (
            <Chip
              key={key}
              onRemove={
                measures.length > 1
                  ? () => setMeasures(measures.filter((m) => m !== key))
                  : undefined
              }
              removeLabel={`Stop showing ${col?.label ?? key}`}
            >
              {col?.label ?? key}
            </Chip>
          )
        })}
        {measureItems.length > 0 && (
          <Menu
            align="left"
            items={measureItems}
            trigger={({ open, toggle }) => (
              <Button
                size="sm"
                aria-haspopup="menu"
                aria-expanded={open}
                onClick={toggle}
              >
                <Plus size={14} /> Add… <ChevronDown size={14} />
              </Button>
            )}
          />
        )}
        <div className="ml-auto flex items-center gap-2">
          <InfoTip label="About summaries">
            Worked out over every record the list shows, with its filters and
            search. A date known only to the year keeps a group of its own when
            grouped by month. A list (tags, links) puts a record in a group for
            each item, so groups can add up to more than the total. Click a
            group to list its records.
          </InfoTip>
          <Menu
            items={TABLE_FORMATS.map((f) => ({
              label: f.name,
              hint: f.hint,
              onClick: () => download(f.id),
            }))}
            trigger={({ open, toggle }) => (
              <Button
                size="sm"
                aria-haspopup="menu"
                aria-expanded={open}
                onClick={toggle}
                disabled={!data || downloading}
              >
                <Download size={14} /> Download <ChevronDown size={14} />
              </Button>
            )}
          />
        </div>
      </div>

      {downloadError && <ErrorState message={downloadError} />}
      {data?.truncated && (
        <p className="text-sm text-fg-muted">
          Only the first {data.limit.toLocaleString()} groups are shown.
        </p>
      )}
      {data?.timezone && (
        <p className="text-xs text-fg-muted">
          Dates and times are grouped in {data.timezone}.
        </p>
      )}

      <div className={isFetching && data ? 'opacity-70' : undefined}>
        <DataTable
          columns={columns}
          rows={rows}
          getRowId={(r) => r.id}
          isLoading={isLoading}
          error={error ? errorMessage(error) : undefined}
          emptyTitle="Nothing to summarise"
          sort={
            list.sort
              ? { key: list.sort.field, direction: list.sort.dir }
              : undefined
          }
          onSortChange={list.toggleSort}
          onRowClick={(r) => {
            if (r.row?.where) onDrill(r.row.where)
          }}
          rowClassName={(r) =>
            r.row === null
              ? 'border-t-2 border-border'
              : r.row.where
                ? 'cursor-pointer'
                : ''
          }
          dense
        />
      </div>
      {by.length === 0 && (
        <p className="text-xs text-fg-muted">
          Add a grouping to break the total down.
        </p>
      )}
    </div>
  )
}
