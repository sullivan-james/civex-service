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
  /** The volume's folder is on a network drive. */
  network: boolean
  /** Files here that nothing uses (garbage collection can reclaim them). */
  unused_files: number
  unused_bytes: number
  /** Files here kept only because a workflow run took them as an input. */
  history_files: number
  history_bytes: number
}

export interface StorageLocation {
  label: string
  path: string
  kind: 'project' | 'home' | 'drive'
  free_bytes: number | null
  total_bytes: number | null
  /** The drive lives on another machine. */
  network: boolean
  /** Where a network drive really is, e.g. nas:/export. */
  source: string | null
}

export interface DirectoryListing {
  path: string
  parent: string | null
  entries: { name: string; path: string }[]
  truncated: boolean
  locations: StorageLocation[]
  /** Why a drive might be missing, where the platform has a known reason. */
  hint: string | null
}

/** How much of a collection's data one volume holds. */
export interface CollectionVolumeShare {
  volume: string
  files: number
  bytes: number
  /** Of those, files another collection uses too. */
  shared_files: number
  state: VolumeStats['state']
  available: boolean
}

/** Where a collection's files are stored. */
export interface CollectionStorageReport {
  collection_id: string
  files: number
  bytes: number
  /** Largest first. */
  volumes: CollectionVolumeShare[]
  /** Used by records but not placed on any volume by the catalog. */
  unlocated_files: number
}

/** What adding a folder as a volume would involve. `problems` block it;
 * `warnings` are worth knowing but don't. */
export interface PathInspection {
  path: string
  exists: boolean
  is_dir: boolean
  writable: boolean
  will_create: boolean
  inside_project: boolean
  same_disk_as_project: boolean | null
  free_bytes: number | null
  total_bytes: number | null
  existing_volume: string | null
  marker_volume: string | null
  has_civex_data: boolean
  is_network: boolean
  problems: string[]
  warnings: string[]
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
  /** The volume the pass was limited to; null when it covered every volume. */
  volume?: string | null
}

export const storeApi = {
  listVolumes: () => api.get<VolumeStats[]>('/store/volumes'),
  allCollectionStorage: () =>
    api.get<CollectionStorageReport[]>('/store/collections'),
  collectionStorage: (collectionId: string) =>
    api.get<CollectionStorageReport>(`/store/collections/${collectionId}`),
  addVolume: (body: {
    name: string
    path: string
    allocated_gb?: number | null
    add_to_queue?: boolean
  }) => api.post<VolumeStats>('/store/volumes', body),
  browse: (path?: string, showHidden = false) => {
    const params = new URLSearchParams()
    if (path) params.set('path', path)
    if (showHidden) params.set('show_hidden', 'true')
    const query = params.toString()
    return api.get<DirectoryListing>(`/store/browse${query ? `?${query}` : ''}`)
  },
  createFolder: (parent: string, name: string) =>
    api.post<{ path: string }>('/store/browse/folder', { parent, name }),
  inspectPath: (path: string) =>
    api.get<PathInspection>(`/store/inspect?path=${encodeURIComponent(path)}`),
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
  /** `force` removes a volume that still holds files or homes collections. */
  removeVolume: (name: string, force = false) =>
    api.delete<void>(`/store/volumes/${name}${force ? '?force=true' : ''}`),
  setQueue: (queue: string[]) => api.put<string[]>('/store/queue', { queue }),
  listPlacements: () => api.get<Placement[]>('/store/placement'),
  setPlacement: (
    collectionId: string,
    body: { volume: string; on_unavailable?: PlacementPolicy },
  ) => api.put<Placement>(`/store/placement/${collectionId}`, body),
  clearPlacement: (collectionId: string) =>
    api.delete<void>(`/store/placement/${collectionId}`),
  runGC: (body: { apply?: boolean; grace_days?: number; volume?: string }) =>
    api.post<GCReport>('/store/gc', body),
}
