import { useMemo } from 'react'
import { useSearchParams } from 'react-router'
import type { Schema } from '../../api/schemas'
import { usePermissions } from '../../hooks/useMe'
import { useSetCharts } from '../../hooks/useSchemas'
import { ChartBoard, OpenChart } from '../charts/ChartBoard'
import { NewChart } from '../charts/NewChart'
import { EmptyState } from '../ui'
import { useFieldTypes } from '../../hooks/useFieldTypes'
import {
  EDIT_CHART,
  NEW_CHART,
  OPEN_CHART_PARAM,
  chartTitle,
  storedChart,
} from '../../utils/charts'
import { filterableFields } from '../../utils/hierarchy'
import { summaryFields } from '../../utils/summary'
import { displayLabel } from '../../utils/naming'

/** A kind's charts (`schemas.charts`): the ones every list of the kind
 * opens with, on the one board, drawn over every record of the kind. Each
 * change is saved at once, for everyone (like a saved filter). */
export function KindCharts({
  schema,
  schemas,
}: {
  schema: Schema
  schemas: Schema[]
}) {
  const { canSomewhere } = usePermissions()
  const save = useSetCharts(schema.name)
  const [sp, setSp] = useSearchParams()
  const fields = useMemo(
    () => filterableFields(schema, schemas),
    [schema, schemas],
  )
  const records = useMemo(() => ({ schema_name: schema.name }), [schema.name])
  const types = useFieldTypes()
  const usable = useMemo(
    () => summaryFields(fields, types?.types ?? []),
    [fields, types],
  )
  const charts = schema.charts ?? []
  const kind = displayLabel(schema.name, schema.label)
  const mayChange = canSomewhere('write_records')
  const setOpen = (id: string | null) =>
    setSp((prev) => {
      const out = new URLSearchParams(prev)
      if (id) out.set(OPEN_CHART_PARAM, id)
      else out.delete(OPEN_CHART_PARAM)
      return out
    })
  const at = sp.get(OPEN_CHART_PARAM) ?? ''
  const open = charts.find((c) => c.id === at)
  const building = at === NEW_CHART && mayChange
  const editing = mayChange
    ? charts.find((c) => EDIT_CHART + c.id === at)
    : undefined
  return (
    <div className="space-y-4">
      {(building || editing) && (
        <NewChart
          key={editing?.id ?? 'new'}
          listed={schema}
          schemas={schemas}
          usable={usable}
          kind={kind}
          records={records}
          initial={editing}
          onAdd={(chart) => {
            save.mutate(
              (charts.some((c) => c.id === chart.id)
                ? charts.map((c) => (c.id === chart.id ? chart : c))
                : [...charts, chart]
              ).map(storedChart),
            )
            setOpen(null)
          }}
          onCancel={() => setOpen(null)}
        />
      )}
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
        <EmptyState title="No charts" />
      ) : (
        <ChartBoard
          charts={charts}
          records={records}
          usable={usable}
          kind={kind}
          schemas={schemas}
          onBuild={building || editing ? undefined : () => setOpen(NEW_CHART)}
          onEdit={(c) => setOpen(EDIT_CHART + c.id)}
          onChange={
            mayChange ? (next) => save.mutate(next.map(storedChart)) : undefined
          }
          onOpen={(c) => setOpen(c.id)}
        />
      )}
    </div>
  )
}
