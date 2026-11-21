import { useMemo } from 'react'
import { useSearchParams } from 'react-router'
import type { Schema } from '../../api/schemas'
import { usePermissions } from '../../hooks/useMe'
import { useSetCharts } from '../../hooks/useSchemas'
import { ChartBoard, OpenChart } from '../charts/ChartBoard'
import { Badge, Button, EmptyState } from '../ui'
import { useSuggestedCharts } from '../explorer/useExplorerCharts'
import { OPEN_CHART_PARAM, chartTitle, storedChart } from '../../utils/charts'
import { defaultColumnNames, filterableFields } from '../../utils/hierarchy'
import { displayLabel } from '../../utils/naming'

/** A kind's charts (`schemas.charts`): the ones every list of the kind
 * opens with, on the one board, drawn over every record of the kind. Each
 * change is saved at once, for everyone (it needs `change_structure`). */
export function KindCharts({
  schema,
  schemas,
}: {
  schema: Schema
  schemas: Schema[]
}) {
  const { can } = usePermissions()
  const save = useSetCharts(schema.name)
  const [sp, setSp] = useSearchParams()
  const fields = useMemo(
    () => filterableFields(schema, schemas),
    [schema, schemas],
  )
  const records = useMemo(() => ({ schema_name: schema.name }), [schema.name])
  const set = schema.charts ?? []
  // With none set, a list of the kind shows suggested charts: so does this
  // tab, by the same rule, until someone keeps or changes them.
  const suggested = useSuggestedCharts(
    schema,
    fields,
    defaultColumnNames(schema),
    records,
    set.length === 0,
  )
  const usable = suggested.usable
  const unsaved = set.length === 0 && suggested.charts.length > 0
  const charts = unsaved ? suggested.charts : set
  const kind = displayLabel(schema.name, schema.label)
  const mayChange = can('change_structure')
  const setOpen = (id: string | null) =>
    setSp((prev) => {
      const out = new URLSearchParams(prev)
      if (id) out.set(OPEN_CHART_PARAM, id)
      else out.delete(OPEN_CHART_PARAM)
      return out
    })
  const open = charts.find((c) => c.id === sp.get(OPEN_CHART_PARAM))
  return (
    <div className="space-y-4">
      {open && (
        <OpenChart
          chart={open}
          title={chartTitle(open, usable, kind, schemas)}
          records={records}
          usable={usable}
          onClose={() => setOpen(null)}
        />
      )}
      {unsaved && (
        <div className="flex items-center gap-2">
          <Badge>Suggested</Badge>
          {mayChange && (
            <Button
              size="sm"
              disabled={save.isPending}
              onClick={() => save.mutate(charts.map(storedChart))}
            >
              Keep these
            </Button>
          )}
        </div>
      )}
      {charts.length === 0 && !mayChange ? (
        <EmptyState title="No charts set" />
      ) : (
        <ChartBoard
          charts={charts}
          records={records}
          usable={usable}
          kind={kind}
          schemas={schemas}
          listed={schema}
          onChange={
            mayChange ? (next) => save.mutate(next.map(storedChart)) : undefined
          }
          onOpen={(c) => setOpen(c.id)}
        />
      )}
    </div>
  )
}
