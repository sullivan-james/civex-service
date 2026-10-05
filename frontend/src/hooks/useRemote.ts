import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { errorMessage } from '../lib/errors'
import { remoteApi, type ResolveBody, type SyncConflict } from '../api/remote'

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

const NONE: SyncConflict[] = []

/** The open conflicts about one thing (a record's page says so). The same list
 * as `useSyncConflicts`, narrowed, so it costs no request of its own, and is not
 * even fetched while there is nothing to review. */
export function useConflictsAbout(entityId: string) {
  const { data: status } = useRemoteStatus()
  const { data } = useQuery({
    queryKey: [...KEY, 'conflicts'],
    queryFn: () => remoteApi.conflicts('open'),
    enabled: (status?.open_conflicts ?? 0) > 0,
    select: (all) => all.filter((c) => c.entity_id === entityId),
  })
  return data ?? NONE
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

/** Settle several at once, one after another, and say which could not be:
 * a value that has changed again since is refused, and the others still go. */
export function useResolveMany() {
  const refresh = useRefreshing()
  return useMutation({
    mutationFn: async ({
      ids,
      take,
    }: {
      ids: string[]
      take: ResolveBody['take']
    }) => {
      const failed: { id: string; message: string }[] = []
      for (const id of ids) {
        try {
          await remoteApi.resolve(id, { take })
        } catch (e) {
          failed.push({ id, message: errorMessage(e) })
        }
      }
      return { done: ids.length - failed.length, failed }
    },
    onSettled: refresh,
  })
}

export function useResolveConflict() {
  const refresh = useRefreshing()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & ResolveBody) =>
      remoteApi.resolve(id, body),
    // Also when it is refused: the list then says what changed (`stale`).
    onSettled: refresh,
  })
}
