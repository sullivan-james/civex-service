import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { storeApi, type PlacementPolicy } from '../api/store'

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

export function useAdoptVolume() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: storeApi.adoptVolume,
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

const PLACEMENT_KEY = ['store', 'placement']

export function usePlacements() {
  return useQuery({
    queryKey: PLACEMENT_KEY,
    queryFn: storeApi.listPlacements,
  })
}

export function useSetPlacement() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      collectionId,
      volume,
      onUnavailable,
    }: {
      collectionId: string
      volume: string
      onUnavailable: PlacementPolicy
    }) =>
      storeApi.setPlacement(collectionId, {
        volume,
        on_unavailable: onUnavailable,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: PLACEMENT_KEY }),
  })
}

export function useClearPlacement() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: storeApi.clearPlacement,
    onSuccess: () => qc.invalidateQueries({ queryKey: PLACEMENT_KEY }),
  })
}
