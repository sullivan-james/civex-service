import { useMemo } from 'react'
import { useSearchParams } from 'react-router'
import type { RecordSelectionBody } from '../../api/records'
import type { Chart, Schema } from '../../api/schemas'
import { useFieldTypes } from '../../hooks/useFieldTypes'
import { useRecordSummary } from '../../hooks/useRecords'
import { useSetCharts } from '../../hooks/useSchemas'
import {
  CHARTS_PARAM,
  OPEN_CHART_PARAM,
  chartsFromParam,
  chartsToParam,
  sameCharts,
  storedChart,
  suggestCharts,
  suggestionCandidates,
  suggestionMeasures,
} from '../../utils/charts'
import type { FilterableField } from '../../utils/hierarchy'
import { summaryFields } from '../../utils/summary'
import { mapFields } from './MapView'

/** The charts beside a list of one kind: the kind's own (`schemas.charts`),
 * or, when it has none set, ones suggested from the listed records; and the
 * person's changes to them, held in the address (`charts`) until they are
 * saved for the kind or put back. Also which chart is opened large
 * (`chart`, a step in history, so Back closes it). */
export function useExplorerCharts(
  listed: Schema | null,
  fields: FilterableField[],
  shownColumns: string[],
  records: RecordSelectionBody,
  enabled: boolean,
) {
  const [sp, setSp] = useSearchParams()
  const types = useFieldTypes()
  const usable = useMemo(
    () => summaryFields(fields, types?.types ?? []),
    [fields, types],
  )
  const own = listed ? chartsFromParam(sp.get(CHARTS_PARAM)) : null
  const kinds = listed?.charts ?? []

  // Suggestions are asked for only while they would be shown.
  const candidates = suggestionCandidates(usable, shownColumns)
  const asking = suggestionMeasures(candidates)
  const suggesting = !!listed && kinds.length === 0 && own === null
  const answer = useRecordSummary(
    suggesting && enabled && asking.length > 0
      ? { ...records, group_by: [], measures: asking }
      : null,
  )
  const suggested = suggesting
    ? suggestCharts(candidates, answer.data, mapFields(fields)[0])
    : []
  const base = kinds.length > 0 ? kinds : suggested
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

  return {
    charts,
    usable,
    /** The charts on screen are the person's own, not the kind's. */
    changed: own !== null,
    loading: suggesting && answer.isLoading,
    set: (next: Chart[]) =>
      change((out) => {
        if (sameCharts(next, base)) out.delete(CHARTS_PARAM)
        else out.set(CHARTS_PARAM, chartsToParam(next))
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
