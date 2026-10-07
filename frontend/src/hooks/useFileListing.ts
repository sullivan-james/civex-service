import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { fileAccessApi, type FilePick } from '../api/fileAccess'

const KEY = 'file-listing'

/** A page of a selection's files and where all of them are. */
export function useFileListing(
  pick: FilePick & { order?: string; offset?: number; limit?: number },
  enabled = true,
) {
  return useQuery({
    queryKey: [KEY, pick],
    queryFn: () => fileAccessApi.files(pick),
    placeholderData: keepPreviousData,
    enabled,
  })
}

/** After an action moves, fetches or removes files, everything that says where
 * files are is asked again. */
function useRefreshPlaces() {
  const qc = useQueryClient()
  return () => {
    for (const key of [KEY, 'records', 'record', 'store', 'remote'])
      qc.invalidateQueries({ queryKey: [key] })
  }
}

export function useFreeUpFiles() {
  const refresh = useRefreshPlaces()
  return useMutation({
    mutationFn: (v: { pick: FilePick; dryRun: boolean }) =>
      fileAccessApi.freeUp(v.pick, v.dryRun),
    onSuccess: (r) => {
      if (r.done) refresh()
    },
  })
}
