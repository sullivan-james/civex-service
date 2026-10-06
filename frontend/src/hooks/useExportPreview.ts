import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { fileAccessApi, type FileSelection } from '../api/fileAccess'

/** What an export would make, worked out as soon as it is wanted and again
 * whenever the choices change: no button to press and nothing that can be out of
 * date. The last answer stays on screen while the next is fetched. */
export function useExportPreview(selection: FileSelection, enabled: boolean) {
  return useQuery({
    queryKey: ['export-preview', selection],
    queryFn: () => fileAccessApi.preview(selection),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })
}
