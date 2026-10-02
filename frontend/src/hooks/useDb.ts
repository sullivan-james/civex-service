import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { dbApi, type MoveTarget } from '../api/db'

const KEY = ['db', 'status']

export function useDbStatus() {
  return useQuery({
    queryKey: KEY,
    queryFn: dbApi.getStatus,
  })
}

export function useMigrateDb() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: dbApi.migrate,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useSetDbUrl() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: dbApi.setUrl,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useSetupDockerDb() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: dbApi.setupDocker,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useTeardownDockerDb() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: dbApi.teardownDocker,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useDbSummary() {
  return useQuery({
    queryKey: ['db', 'summary'],
    queryFn: dbApi.getSummary,
  })
}

export function useDbMoves() {
  return useQuery({
    queryKey: ['db', 'moves'],
    queryFn: dbApi.listMoves,
  })
}

export function useTestConnection() {
  return useMutation({ mutationFn: (t: MoveTarget) => dbApi.testConnection(t) })
}

export function usePreflightMove() {
  return useMutation({ mutationFn: (t: MoveTarget) => dbApi.preflightMove(t) })
}

export function useStartMove() {
  return useMutation({ mutationFn: (t: MoveTarget) => dbApi.startMove(t) })
}

/** Polls a running move every half second, and stops once it has ended. */
export function useMoveJob(id: string | null) {
  return useQuery({
    queryKey: ['db', 'move', id],
    queryFn: () => dbApi.getMove(id!),
    enabled: !!id,
    refetchInterval: (query) =>
      query.state.data && query.state.data.status !== 'running' ? false : 500,
  })
}

export function useCancelMove() {
  return useMutation({ mutationFn: (id: string) => dbApi.cancelMove(id) })
}

/** After a move or a revert the project is on a different database, so
 * everything the app has cached came from the old one. */
export function useRevertMove() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => dbApi.revertMove(id),
    onSuccess: () => qc.invalidateQueries(),
  })
}
