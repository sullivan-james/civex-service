import { useMemo } from 'react'
import { useSearchParams } from 'react-router'
import type { Chart, Schema } from '../../api/schemas'
import { useFieldTypes } from '../../hooks/useFieldTypes'
import { useSetCharts } from '../../hooks/useSchemas'
import {
  CHARTS_PARAM,
  NEW_CHART,
  OPEN_CHART_PARAM,
  chartsFromParam,
  chartsToParam,
  sameCharts,
  storedChart,
} from '../../utils/charts'
import type { FilterableField } from '../../utils/hierarchy'
import { summaryFields } from '../../utils/summary'

/** The charts beside a list of one kind: the kind's own (`schemas.charts`;
 * none until someone adds one), and the person's changes to them, held in
 * the address (`charts`) until they are saved for the kind or put back. Also
 * which chart is opened large (`chart`, a step in history, so Back closes
 * it). */
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
  const own = listed ? chartsFromParam(sp.get(CHARTS_PARAM)) : null
  const base = listed?.charts ?? []
  const charts = own ?? base

  const save = useSetCharts(listed?.name ?? '')
  const change = (edit: (out: URLSearchParams) => void, replace = true) =>
    setSp(
      (prev) => {
        const out = new URLSearchParams(prev)
        edit(out)
        return out
      },
      { replace },
    )
  const open = charts.find((c) => c.id === sp.get(OPEN_CHART_PARAM)) ?? null
  const writeCharts = (out: URLSearchParams, next: Chart[]) => {
    if (sameCharts(next, base)) out.delete(CHARTS_PARAM)
    else out.set(CHARTS_PARAM, chartsToParam(next))
  }

  return {
    charts,
    usable,
    /** The charts on screen are the person's own, not the kind's. */
    changed: own !== null,
    set: (next: Chart[]) => change((out) => writeCharts(out, next)),
    /** A chart is being built (`chart=new`, a step in history). */
    building: sp.get(OPEN_CHART_PARAM) === NEW_CHART,
    build: () => change((out) => out.set(OPEN_CHART_PARAM, NEW_CHART), false),
    /** The chart built joins the others, and the builder closes: one change. */
    add: (chart: Chart) =>
      change((out) => {
        writeCharts(out, [...charts, chart])
        out.delete(OPEN_CHART_PARAM)
      }),
    putBack: () => change((out) => out.delete(CHARTS_PARAM)),
    /** Use these for every list of the kind. */
    saveForKind: () =>
      save.mutate(charts.map(storedChart), {
        onSuccess: () => change((out) => out.delete(CHARTS_PARAM)),
      }),
    saving: save.isPending,
    open,
    setOpen: (chart: Chart | null) =>
      change((out) => {
        if (chart) out.set(OPEN_CHART_PARAM, chart.id)
        else out.delete(OPEN_CHART_PARAM)
      }, false),
  }
}

export type ExplorerCharts = ReturnType<typeof useExplorerCharts>
