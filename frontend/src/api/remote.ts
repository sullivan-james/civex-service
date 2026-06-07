import { api } from './client'

export interface RemoteStatus {
  url: string
  last_pushed_at: string | null
  last_pulled_at: string | null
}

export interface SyncResult {
  schemas: number
  datasets: number
  records: number
  objects: number
}

export const remoteApi = {
  status: () => api.get<RemoteStatus>('/remote'),
  push:   () => api.post<SyncResult>('/remote/push', {}),
  pull:   () => api.post<SyncResult>('/remote/pull', {}),
}
