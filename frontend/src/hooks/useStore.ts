import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { storeApi } from '../api/store'

const KEY = ['store', 'volumes']

export function useVolumes() {
  return useQuery({
    queryKey: KEY,
    queryFn: storeApi.listVolumes,
    refetchInterval: 30_000,
  })
}

export function useAddVolume() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: storeApi.addVolume,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useUpdateVolume() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      name,
      body,
    }: {
      name: string
      body: Parameters<typeof storeApi.updateVolume>[1]
    }) => storeApi.updateVolume(name, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useRemoveVolume() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: storeApi.removeVolume,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useSetQueue() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: storeApi.setQueue,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useRunGC() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: storeApi.runGC,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}
