import { api } from './client'

export interface VolumeStats {
  name: string
  path: string
  allocated_gb: number | null
  civex_used_bytes: number | null
  disk_free_bytes: number | null
  disk_total_bytes: number | null
  available: boolean
  warning: boolean
  in_queue: boolean
}

export const storeApi = {
  listVolumes: () => api.get<VolumeStats[]>('/store/volumes'),
  addVolume: (body: { name: string; path: string; allocated_gb?: number | null }) =>
    api.post<VolumeStats>('/store/volumes', body),
  updateVolume: (name: string, body: { path?: string; allocated_gb?: number | null; clear_allocation?: boolean }) =>
    api.patch<VolumeStats>(`/store/volumes/${name}`, body),
  removeVolume: (name: string) => api.delete<void>(`/store/volumes/${name}`),
  setQueue: (queue: string[]) => api.put<string[]>('/store/queue', { queue }),
}
