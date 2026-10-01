import { useQuery } from '@tanstack/react-query'
import { recordsApi } from '../api/records'
import { useView } from './useViews'

/** How many records a saved filter matches right now, for pins and Home.
 * Keyed under `records` so any record change refreshes it. `undefined`
 * while loading, or when the view no longer exists. */
export function useViewCount(
  schemaName: string | undefined,
  viewName: string | undefined,
) {
  const view = useView(schemaName ?? '', viewName ?? '')
  const count = useQuery({
    queryKey: ['records', 'view-count', schemaName, view.data?.filter_tree],
    queryFn: () =>
      recordsApi.listBySchema(schemaName!, {
        schema: schemaName,
        filter: view.data!.filter_tree,
        limit: 1,
      }),
    enabled: !!schemaName && !!view.data,
    select: (page) => page.total,
  })
  return {
    count: count.data,
    /** The view was deleted or renamed since it was pinned. */
    missing: view.isError,
  }
}
