import { useQuery } from '@tanstack/react-query'
import { filesApi } from '../api/files'

/** Where one file's content is and what uses it. Fetched only when asked for
 * (the details panel opening), never per file in a list. */
export function useFileInfo(sha256: string, enabled = true) {
  return useQuery({
    queryKey: ['files', 'info', sha256],
    queryFn: () => filesApi.info(sha256),
    enabled,
    retry: false,
    staleTime: 5_000,
  })
}
