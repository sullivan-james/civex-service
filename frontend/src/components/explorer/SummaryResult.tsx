import type { RecordSummary, SummaryRow } from '../../api/records'
import { useFieldTypes } from '../../hooks/useFieldTypes'
import { DataTable, ErrorState, type DataTableColumn } from '../ui'
import { SummaryChart } from './SummaryChart'
import { errorMessage } from '../../lib/errors'
import type { FilterTreeWire } from '../../utils/filterTree'
import { compareSummaryCells, formatSummaryValue } from '../../utils/summary'

const TOTAL_ID = '__total'

type Row = { id: string; row: SummaryRow | null; cells: unknown[] }

/** A summary drawn as a table (groups, their measures, a total) or a chart,
 * without the controls that chose it: the explorer's Summary shows it under
 * its sentence, and an analysis card on the Analytics page shows it alone.
 * Sorting, the chart's measure and drilling into a group are offered only
 * when their handlers are given. */
export function SummaryResult({
  data,
  isLoading = false,
  isFetching = false,
  error,
  show,
  sort,
  onSort,
  chartMeasure,
  onChartMeasure,
  onDrill,
  dense = true,
}: {
  data: RecordSummary | undefined
  isLoading?: boolean
  isFetching?: boolean
  error?: unknown
  show: 'table' | 'chart'
  sort: { column: string; direction: 'asc' | 'desc' } | null
  onSort?: (column: string) => void
  chartMeasure: string | null
  onChartMeasure?: (key: string) => void
  onDrill?: (where: FilterTreeWire) => void
  dense?: boolean
}) {
  const types = useFieldTypes()
  const measureHelp = new Map(
    (types?.summary_measures ?? []).map((m) => [m.key, m.help]),
  )
  const groupCols = data?.group_columns ?? []
  const measureCols = data?.measure_columns ?? []
  const rows: Row[] = (data?.rows ?? []).map((row, i) => ({
    id: String(i),
    row,
    cells: [...row.groups.map((g) => g.value), ...row.values],
  }))
  const sortIndex = sort
    ? [...groupCols, ...measureCols].findIndex((c) => c.key === sort.column)
    : -1
  if (sort && sortIndex >= 0) {
    const dir = sort.direction === 'desc' ? -1 : 1
    rows.sort(
      (a, b) =>
        dir * compareSummaryCells(a.cells[sortIndex], b.cells[sortIndex]),
    )
  }
  if (data)
    rows.push({
      id: TOTAL_ID,
      row: null,
      cells: [...groupCols.map(() => null), ...data.total],
    })

  const columns: DataTableColumn<Row>[] = [
    ...groupCols.map<DataTableColumn<Row>>((c, i) => ({
      key: c.key,
      header: c.label,
      sortable: !!onSort,
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
      headerTitle: measureHelp.get(c.measure),
      align: 'right',
      sortable: !!onSort,
      render: (r) => (
        <span className={r.row === null ? 'font-semibold' : undefined}>
          {formatSummaryValue(r.cells[groupCols.length + i])}
        </span>
      ),
    })),
  ]

  return (
    <div className="space-y-2">
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
        {show === 'chart' ? (
          error ? (
            <ErrorState message={errorMessage(error)} />
          ) : data ? (
            <SummaryChart
              summary={data}
              measureKey={chartMeasure}
              onMeasure={onChartMeasure}
              onDrill={onDrill}
            />
          ) : (
            <p className="text-sm text-fg-muted">Working it out…</p>
          )
        ) : (
          <DataTable
            columns={columns}
            rows={rows}
            getRowId={(r) => r.id}
            isLoading={isLoading}
            error={error ? errorMessage(error) : undefined}
            emptyTitle="Nothing to summarise"
            sort={
              sort ? { key: sort.column, direction: sort.direction } : undefined
            }
            onSortChange={onSort}
            onRowClick={
              onDrill
                ? (r) => {
                    if (r.row?.where) onDrill(r.row.where)
                  }
                : undefined
            }
            rowClassName={(r) =>
              r.row === null
                ? 'border-t-2 border-border'
                : r.row.where && onDrill
                  ? 'cursor-pointer'
                  : ''
            }
            dense={dense}
          />
        )}
      </div>
    </div>
  )
}
