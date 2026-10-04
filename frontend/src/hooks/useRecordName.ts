import { useQuery, type QueryClient } from '@tanstack/react-query'
import { recordsApi, type RecordLabel } from '../api/records'
import { createBatcher } from '../utils/batcher'

/** Every name asked for while a screen is drawn goes out as one request. */
const labels = createBatcher<string, RecordLabel>(async (ids) => {
  const found = await recordsApi.labels(ids)
  return new Map(found.map((l) => [l.id, l]))
})

const KEY = 'record-name'

/** A record's name as it is now, from its id alone, wherever only the id was
 * kept (a run's records, a pin, a link). Nothing is copied into history: the
 * name is looked up when shown, so a rename or a new name template shows
 * everywhere. Many of these on one screen share one request. `undefined` while
 * it loads, and for an id that is no longer a record. */
export function useRecordName(id: string | null | undefined) {
  return useQuery({
    queryKey: [KEY, id],
    queryFn: async () => (await labels.load(id as string)) ?? null,
    enabled: !!id,
    // Fresh enough to share between rows and quick page changes; a record edit
    // refreshes it at once (see `invalidateRecordNames`).
    staleTime: 15_000,
  })
}

/** Call wherever a record, or a schema's name template, is changed. */
export function invalidateRecordNames(qc: QueryClient) {
  return qc.invalidateQueries({ queryKey: [KEY] })
}
