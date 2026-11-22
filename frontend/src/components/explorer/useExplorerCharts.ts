import { useMemo } from 'react'
import { useSearchParams } from 'react-router'
import type { Chart, Schema } from '../../api/schemas'
import { useFieldTypes } from '../../hooks/useFieldTypes'
import { useSetCharts } from '../../hooks/useSchemas'
import {
  EDIT_CHART,
  NEW_CHART,
  OPEN_CHART_PARAM,
  storedChart,
} from '../../utils/charts'
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

  const at = sp.get(OPEN_CHART_PARAM) ?? ''
  const byId = (id: string) => charts.find((c) => c.id === id) ?? null

  return {
    charts,
    usable,
    set,
    /** A chart is being built (`chart=new`). */
    building: at === NEW_CHART,
    build: () => show(NEW_CHART),
    /** The chart being changed (`chart=edit-<id>`). */
    editing: at.startsWith(EDIT_CHART)
      ? byId(at.slice(EDIT_CHART.length))
      : null,
    edit: (chart: Chart) => show(EDIT_CHART + chart.id),
    /** The chart built or changed joins the kind's (in its place when it
     * was there), and the builder closes. */
    keep: (chart: Chart) => {
      set(
        charts.some((c) => c.id === chart.id)
          ? charts.map((c) => (c.id === chart.id ? chart : c))
          : [...charts, chart],
      )
      show(null)
    },
    open: byId(at),
    setOpen: (chart: Chart | null) => show(chart?.id ?? null),
  }
}

export type ExplorerCharts = ReturnType<typeof useExplorerCharts>
