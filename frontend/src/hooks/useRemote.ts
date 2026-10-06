import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  remoteApi,
  type Authority,
  type ResolveBody,
  type ResolveManyBody,
  type SyncConflict,
} from '../api/remote'

const KEY = ['remote']

/** Where the project stands with its authority. Polls quickly while a sync is
 * running or one is waiting to go, slowly otherwise. */
export function useRemoteStatus() {
  return useQuery({
    queryKey: KEY,
    queryFn: remoteApi.status,
    refetchInterval: (q) => {
      const s = q.state.data
      // Copying shows a bar, so it is read often enough to move.
      if (s?.connecting || s?.progress) return 1000
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

/** A moment as a time, reading one with no zone as UTC (the server's). */
function utcMs(iso: string): number {
  return Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`)
}

/** A record's conflicts for its merge view: the ones still open, and the ones
 * settled since the page was opened (so a row stays on screen, marked settled,
 * instead of vanishing under the person's hand). */
export function useMergeConflicts(entityId: string, enabled: boolean) {
  // A minute early, so a clock a little behind the server's still shows them.
  const [since] = useState(() => Date.now() - 60_000)
  return useQuery({
    queryKey: [...KEY, 'conflicts', 'record', entityId],
    queryFn: () => remoteApi.conflicts('all', entityId),
    enabled,
    select: (all) =>
      all.filter(
        (c) =>
          c.status === 'open' ||
          // A refusal a later attempt replaced was never the person's to settle.
          (c.resolution !== 'replaced' &&
            c.resolved_at !== null &&
            utcMs(c.resolved_at) >= since),
      ),
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
    mutationFn: ({ url, token }: { url: string; token?: string }) =>
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

/** Settle many in one request: the ticked ones (`ids`) or everything matching
 * (`kind`, `record_id`, or all). Those that fail their checks stay open and are
 * listed in the answer; the rest still go. A `dry_run` only counts, and changes
 * nothing, so it does not refresh. */
export function useResolveMany() {
  const refresh = useRefreshing()
  return useMutation({
    mutationFn: (body: ResolveManyBody) => remoteApi.resolveMany(body),
    onSettled: (_data, _error, body) => {
      if (!body.dry_run) refresh()
    },
  })
}

/** Take back what was settled with "keep theirs": it changed nothing, so the
 * conflicts simply open again. */
export function useReopenConflicts() {
  const refresh = useRefreshing()
  return useMutation({
    mutationFn: (ids: string[]) => remoteApi.reopen(ids),
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

/** This project as an authority (what `civex sync authority|device` do). */
export function useAuthority() {
  return useQuery({
    queryKey: [...KEY, 'authority'],
    queryFn: remoteApi.authority,
  })
}

export function useAuthorityActions() {
  const qc = useQueryClient()
  const settle = (data: Authority) => {
    qc.setQueryData([...KEY, 'authority'], data)
    qc.invalidateQueries({ queryKey: KEY, exact: true })
  }
  return {
    setServing: useMutation({
      mutationFn: remoteApi.setServing,
      onSuccess: settle,
    }),
    addDevice: useMutation({
      mutationFn: remoteApi.addDevice,
      onSuccess: settle,
    }),
    revokeDevice: useMutation({
      mutationFn: remoteApi.revokeDevice,
      onSuccess: settle,
    }),
  }
}
