import { useMemo } from 'react'
import { useSearchParams } from 'react-router'
import type { Chart, Schema } from '../../api/schemas'
import { useFieldTypes } from '../../hooks/useFieldTypes'
import { useSetCharts } from '../../hooks/useSchemas'
import { NEW_CHART, OPEN_CHART_PARAM, storedChart } from '../../utils/charts'
import type { FilterableField } from '../../utils/hierarchy'
import { summaryFields } from '../../utils/summary'

/** The charts beside a list of one kind: the kind's own (`schemas.charts`;
 * none until someone adds one). Adding, removing or moving one saves it for
 * the kind at once, for everyone, like a saved filter: there is no unsaved
 * state. Also which chart is opened large and whether one is being built
 * (`chart` in the address, a step in history, so Back closes it). */
export function useExplorerCharts(
  listed: Schema | null,
  fields: FilterableField[],
) {
  const [sp, setSp] = useSearchParams()
  const types = useFieldTypes()
  const usable = useMemo(
    () => summaryFields(fields, types?.types ?? []),
    [fields, types],
  )
  const charts = listed?.charts ?? []
  const save = useSetCharts(listed?.name ?? '')
  const show = (id: string | null) =>
    setSp((prev) => {
      const out = new URLSearchParams(prev)
      if (id) out.set(OPEN_CHART_PARAM, id)
      else out.delete(OPEN_CHART_PARAM)
      return out
    })
  const set = (next: Chart[]) => save.mutate(next.map(storedChart))

  return {
    charts,
    usable,
    set,
    /** A chart is being built (`chart=new`). */
    building: sp.get(OPEN_CHART_PARAM) === NEW_CHART,
    build: () => show(NEW_CHART),
    /** The chart built joins the kind's, and the builder closes. */
    add: (chart: Chart) => {
      set([...charts, chart])
      show(null)
    },
    open: charts.find((c) => c.id === sp.get(OPEN_CHART_PARAM)) ?? null,
    setOpen: (chart: Chart | null) => show(chart?.id ?? null),
  }
}

export type ExplorerCharts = ReturnType<typeof useExplorerCharts>
