import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { remoteApi } from '../api/remote'

const KEY = ['remote']

/** Where the project stands with its authority. Polls quickly while a sync is
 * running or one is waiting to go, slowly otherwise. */
export function useRemoteStatus() {
  return useQuery({
    queryKey: KEY,
    queryFn: remoteApi.status,
    refetchInterval: (q) => {
      const s = q.state.data
      if (!s?.configured) return 30_000
      return s.running || s.pending > 0 ? 2000 : 15_000
    },
  })
}

export function useSyncConflicts(enabled: boolean) {
  return useQuery({
    queryKey: [...KEY, 'conflicts'],
    queryFn: () => remoteApi.conflicts('open'),
    enabled,
  })
}

/** Everything that changes what a sync shows: the status, the conflicts, and the
 * data itself, which a sync may have changed under the page. */
function useRefreshing() {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: KEY })
    qc.invalidateQueries({ queryKey: ['records'] })
    qc.invalidateQueries({ queryKey: ['audit'] })
  }
}

export function useConnectRemote() {
  const refresh = useRefreshing()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ url, token }: { url: string; token: string }) =>
      remoteApi.connect(url, token),
    onSuccess: () => {
      refresh()
      qc.invalidateQueries()
    },
  })
}

export function useDisconnectRemote() {
  const refresh = useRefreshing()
  return useMutation({ mutationFn: remoteApi.disconnect, onSuccess: refresh })
}

export function useSyncNow() {
  const refresh = useRefreshing()
  return useMutation({ mutationFn: remoteApi.syncNow, onSuccess: refresh })
}

export function useUpdateRemote() {
  const refresh = useRefreshing()
  return useMutation({ mutationFn: remoteApi.update, onSuccess: refresh })
}

export function useResolveConflict() {
  const refresh = useRefreshing()
  return useMutation({
    mutationFn: ({ id, take }: { id: string; take: 'mine' | 'theirs' }) =>
      remoteApi.resolve(id, take),
    onSuccess: refresh,
  })
}
