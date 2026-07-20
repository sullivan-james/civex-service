import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { dbApi } from '../api/db'

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
