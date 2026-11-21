import { useMemo } from 'react'
import { useSearchParams } from 'react-router'
import type { Schema } from '../../api/schemas'
import { useFieldTypes } from '../../hooks/useFieldTypes'
import { usePermissions } from '../../hooks/useMe'
import { useSetCharts } from '../../hooks/useSchemas'
import { ChartBoard, OpenChart } from '../charts/ChartBoard'
import { EmptyState } from '../ui'
import { OPEN_CHART_PARAM, chartTitle, storedChart } from '../../utils/charts'
import { filterableFields } from '../../utils/hierarchy'
import { displayLabel } from '../../utils/naming'
import { summaryFields } from '../../utils/summary'

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
  const types = useFieldTypes()
  const { can } = usePermissions()
  const save = useSetCharts(schema.name)
  const [sp, setSp] = useSearchParams()
  const usable = useMemo(
    () => summaryFields(filterableFields(schema, schemas), types?.types ?? []),
    [schema, schemas, types],
  )
  const charts = schema.charts ?? []
  const kind = displayLabel(schema.name, schema.label)
  const records = { schema_name: schema.name }
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
