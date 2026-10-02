import {
  keepPreviousData,
  useQuery,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query'
import { storeApi, type PlacementPolicy } from '../api/store'

const KEY = ['store', 'volumes']
const PLACEMENT_KEY = ['store', 'placement']

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
    mutationFn: ({ name, force }: { name: string; force?: boolean }) =>
      storeApi.removeVolume(name, force),
    // Removing a volume can also clear collections' homes.
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY })
      qc.invalidateQueries({ queryKey: PLACEMENT_KEY })
    },
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

/** The folders inside `path` (home when undefined), for the folder browser. */
export function useBrowse(path: string | undefined, showHidden: boolean) {
  return useQuery({
    queryKey: ['store', 'browse', path ?? '', showHidden],
    queryFn: () => storeApi.browse(path, showHidden),
    retry: false,
    staleTime: 5_000,
    // Keep the places and the last folder on screen while the next one loads.
    placeholderData: keepPreviousData,
  })
}

export function useCreateFolder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ parent, name }: { parent: string; name: string }) =>
      storeApi.createFolder(parent, name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['store', 'browse'] }),
  })
}

/** What adding `path` as a volume would involve; idle until there is a path. */
export function useInspectPath(path: string) {
  return useQuery({
    queryKey: ['store', 'inspect', path],
    queryFn: () => storeApi.inspectPath(path),
    enabled: path.trim() !== '',
    retry: false,
    staleTime: 0,
    gcTime: 0,
  })
}

/** Give several collections the same home (or clear it, with an empty
 * `volume`) in one go. */
export function useBulkPlacement() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      collectionIds,
      volume,
      onUnavailable = 'spill',
    }: {
      collectionIds: string[]
      volume: string
      onUnavailable?: PlacementPolicy
    }) => {
      for (const id of collectionIds) {
        if (volume === '') await storeApi.clearPlacement(id)
        else
          await storeApi.setPlacement(id, {
            volume,
            on_unavailable: onUnavailable,
          })
      }
    },
    onSettled: () => qc.invalidateQueries({ queryKey: PLACEMENT_KEY }),
  })
}
