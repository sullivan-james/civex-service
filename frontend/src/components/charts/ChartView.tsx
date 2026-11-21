import { recordsApi, type RecordSelectionBody } from '../../api/records'
import type { Chart } from '../../api/schemas'
import { useRecordSummary } from '../../hooks/useRecords'
import { Button, ErrorState, Menu, Skeleton } from '../ui'
import { Download } from '../ui/icons'
import { useToast } from '../ui/ToastProvider'
import { saveBlob } from '../files/fileFlows'
import { MapView } from '../explorer/MapView'
import { SummaryChart } from '../explorer/SummaryChart'
import { SummaryResult } from '../explorer/SummaryResult'
import { errorMessage } from '../../lib/errors'
import { filterForChart, litBars, toggleBar } from '../../utils/chartFilter'
import type { FilterTreeWire } from '../../utils/filterTree'
import type { FilterableField } from '../../utils/hierarchy'
import { splitGroupKey } from '../../utils/summary'
import { TABLE_FORMATS } from '../../utils/tableFormats'

/** The field a chart's bars are of, from its first grouping (`site`,
 * `kind.field:month`): what a click on a bar filters by. */
function barField(chart: Chart, listed: string) {
  const first = chart.group_by[0]
  if (!first) return undefined
  const name = splitGroupKey(first).field
  const dot = name.lastIndexOf('.')
  return dot < 0
    ? { field: name, schema_name: listed }
    : { field: name.slice(dot + 1), schema_name: name.slice(0, dot) }
}

export interface ChartViewProps {
  chart: Chart
  /** The records it counts: a list's own query, or a card's. */
  records: RecordSelectionBody
  /** The kind's fields and its relatives' (for a map's field). */
  fields: FilterableField[]
  /** Set where bars filter the records listed: called with the filter a
   * click leaves (`utils/chartFilter`, the one rule). */
  onFilter?: (filter: FilterTreeWire | null) => void
  /** Opened large: the full chart or map, with its table of numbers. */
  large?: boolean
  /** False: don't ask yet (the list is still loading, or too big). */
  enabled?: boolean
}

/** One chart, drawn: the one renderer behind a kind's charts, the
 * explorer's column, the Analytics page and a chart opened large. Bars are
 * one `summary` call over `records`; a map is one `points` call. Where
 * `onFilter` is given, a bar is a button that adds or removes its value in
 * the filter, the chosen bars are lit, and the chart counts without the
 * condition on its own field so the others stay to pick. */
export function ChartView({
  chart,
  records,
  fields,
  onFilter,
  large = false,
  enabled = true,
}: ChartViewProps) {
  const toast = useToast()
  const listed = records.schema_name ?? ''
  const of = barField(chart, listed)
  const filter = records.filter as FilterTreeWire | null
  const body =
    chart.map || !enabled
      ? null
      : {
          ...records,
          filter: onFilter ? filterForChart(filter, of, listed) : filter,
          group_by: chart.group_by,
          measures: chart.measures.length ? chart.measures : ['count'],
        }
  const { data, isLoading, isFetching, error } = useRecordSummary(body)

  if (chart.map)
    return enabled ? (
      <MapView
        records={records}
        fields={fields}
        field={chart.map}
        compact={!large}
      />
    ) : null
  if (error) return <ErrorState message={errorMessage(error)} />
  if (!data) return <Skeleton className={large ? 'h-72' : 'h-24'} />

  const onDrill = onFilter
    ? (where: FilterTreeWire) => onFilter(toggleBar(filter, where, of, listed))
    : undefined
  const lit = onFilter ? litBars(filter, of, listed) : null
  const drawn = (
    <SummaryChart
      summary={data}
      measureKey={chart.chart_measure ?? null}
      onDrill={onDrill}
      compact={!large}
      lit={lit}
    />
  )
  if (!large)
    return (
      <div className={isFetching ? 'opacity-70' : undefined}>
        {chart.group_by.length === 0 ? (
          <SummaryResult
            data={data}
            isLoading={isLoading}
            show="table"
            sort={null}
            chartMeasure={null}
          />
        ) : (
          drawn
        )}
      </div>
    )

  async function download(format: string) {
    if (!body) return
    try {
      const got = await recordsApi.summaryFile(body, format)
      saveBlob(got.blob, got.filename ?? `numbers.${format}`)
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }
  return (
    <div className="space-y-3">
      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <div className="min-w-0">{chart.group_by.length > 0 && drawn}</div>
        <div className="min-w-0">
          <SummaryResult
            data={data}
            isLoading={isLoading}
            isFetching={isFetching}
            show="table"
            sort={chart.sort ?? null}
            chartMeasure={null}
            onDrill={onDrill}
          />
        </div>
      </div>
      <Menu
        align="left"
        items={TABLE_FORMATS.map((f) => ({
          label: f.name,
          onClick: () => download(f.id),
        }))}
        trigger={({ open, toggle }) => (
          <Button
            size="sm"
            aria-haspopup="menu"
            aria-expanded={open}
            onClick={toggle}
          >
            <Download size={14} /> Download numbers
          </Button>
        )}
      />
    </div>
  )
}
