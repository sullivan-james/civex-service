import { useQueries } from '@tanstack/react-query'
import { recordsApi } from '../../api/records'
import type { RecordLabels } from '../../utils/filterLabels'
import { recordLabel } from '../records/RecordSearchPicker'

/** Display names for record ids, fetched once each. Shares the
 * `['record', id]` cache with the record page and the reference pickers, so
 * a record already seen costs nothing. Ids not fetched yet, or that no
 * longer resolve, are simply absent. */
export function useRecordLabels(ids: string[]): RecordLabels {
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: ['record', id],
      queryFn: () => recordsApi.get(id),
      staleTime: 60_000,
      retry: false,
    })),
    // Structurally shared, so the object only changes when a name does.
    combine: (results) =>
      Object.fromEntries(
        results.flatMap((r, i) =>
          r.data ? [[ids[i], recordLabel(r.data)]] : [],
        ),
      ),
  })
}
