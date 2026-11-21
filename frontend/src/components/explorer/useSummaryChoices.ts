import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router'
import { queryBody, type SummaryRequest } from '../../api/records'
import type { RecordQueryParams } from '../../api/query'
import { useFieldTypes } from '../../hooks/useFieldTypes'
import type { FilterableField } from '../../utils/hierarchy'
import {
  SUMMARY_NS,
  defaultGrouping,
  summaryChoices,
  summaryFields,
  type SummaryChoices,
} from '../../utils/summary'

/** The explorer's Summary choices, held in the address (`sum.*`), with what
 * they make: the groupings shown (the chosen ones, or `defaultGrouping` when
 * none was chosen, so the screen is never blank), the measures, and the body
 * the server is asked. The one reading of them, shared by the Summary itself
 * and the explorer's Export menu ("This summary as a table"). */
export function useSummaryChoices(
  query: RecordQueryParams,
  collection: string | undefined,
  fields: FilterableField[],
) {
  const [sp, setSp] = useSearchParams()
  const types = useFieldTypes()
  const usable = useMemo(
    () => summaryFields(fields, types?.types ?? []),
    [fields, types],
  )
  const choices: SummaryChoices = summaryChoices(sp)
  // `sum.by` absent: nothing chosen yet, so the default; present and empty:
  // chosen to be one total.
  const chosen = sp.has(`${SUMMARY_NS}by`)
  const by = chosen ? choices.by : defaultGrouping(usable)
  const measures = choices.measures.length ? choices.measures : ['count']

  const set = useCallback(
    (patch: Partial<Record<'by' | 'm' | 'sort' | 'view' | 'y', string>>) =>
      setSp(
        (prev) => {
          const next = new URLSearchParams(prev)
          for (const [k, v] of Object.entries(patch)) {
            // `by` keeps an empty value: one total, on purpose.
            if (v === undefined || (v === '' && k !== 'by'))
              next.delete(SUMMARY_NS + k)
            else next.set(SUMMARY_NS + k, v)
          }
          return next
        },
        { replace: true },
      ),
    [setSp],
  )

  const body: SummaryRequest | null = query.schema
    ? {
        ...queryBody({ ...query, sort: undefined }, collection),
        group_by: by,
        measures,
      }
    : null

  return {
    choices,
    by,
    /** Whether the groupings are the default (nothing chosen yet). */
    byDefault: !chosen,
    measures,
    usable,
    types,
    body,
    set,
    setBy: (next: string[]) => set({ by: next.join(',') }),
    setMeasures: (next: string[]) =>
      set({
        m: next.length === 1 && next[0] === 'count' ? '' : next.join(','),
      }),
  }
}

export type SummaryChoicesState = ReturnType<typeof useSummaryChoices>
