import { api } from './client'

export interface VolumeStats {
  name: string
  path: string
  allocated_gb: number | null
  civex_used_bytes: number | null
  disk_free_bytes: number | null
  disk_total_bytes: number | null
  available: boolean
  state: 'online' | 'offline' | 'wrong_drive' | 'readonly' | 'retired'
  reason: string
  fix: string
  warning: boolean
  in_queue: boolean
}

export type PlacementPolicy = 'spill' | 'fail'

export interface Placement {
  collection_id: string
  /** null when the collection no longer exists. */
  collection_name: string | null
  volume: string
  on_unavailable: PlacementPolicy
}

export interface StoredObject {
  sha256: string
  volume: string
  size: number
  mtime: number
}

export interface GCReport {
  dry_run: boolean
  grace_days: number
  scanned: number
  referenced: number
  protected_by_grace: number
  deleted_count: number
  deleted_bytes: number
  deleted: StoredObject[]
  stale_scratch_removed: number
}

export const storeApi = {
  listVolumes: () => api.get<VolumeStats[]>('/store/volumes'),
  addVolume: (body: {
    name: string
    path: string
    allocated_gb?: number | null
  }) => api.post<VolumeStats>('/store/volumes', body),
  updateVolume: (
    name: string,
    body: {
      path?: string
      allocated_gb?: number | null
      clear_allocation?: boolean
    },
  ) => api.patch<VolumeStats>(`/store/volumes/${name}`, body),
  adoptVolume: (name: string) =>
    api.post<VolumeStats>(`/store/volumes/${name}/adopt`, {}),
  removeVolume: (name: string) => api.delete<void>(`/store/volumes/${name}`),
  setQueue: (queue: string[]) => api.put<string[]>('/store/queue', { queue }),
  listPlacements: () => api.get<Placement[]>('/store/placement'),
  setPlacement: (
    collectionId: string,
    body: { volume: string; on_unavailable?: PlacementPolicy },
  ) => api.put<Placement>(`/store/placement/${collectionId}`, body),
  clearPlacement: (collectionId: string) =>
    api.delete<void>(`/store/placement/${collectionId}`),
  runGC: (body: { apply?: boolean; grace_days?: number }) =>
    api.post<GCReport>('/store/gc', body),
}
