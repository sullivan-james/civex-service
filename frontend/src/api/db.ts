import { api } from './client'

export interface MigrationStatus {
  current_revision: string | null
  head_revision: string | null
  up_to_date: boolean
  error: string | null
}

export interface DockerStatus {
  name: string
  exists: boolean
  running: boolean
  volume_exists: boolean
}

export interface DbStatus {
  url: string
  dialect: string
  docker_managed: boolean
  migration: MigrationStatus
  docker: DockerStatus | null
}

export const dbApi = {
  getStatus: () => api.get<DbStatus>('/db/status'),
  migrate: () => api.post<DbStatus>('/db/migrate', {}),
  setUrl: (url: string) => api.patch<DbStatus>('/db/config', { url }),
  setupDocker: () => api.post<DbStatus>('/db/docker/setup', {}),
  teardownDocker: () => api.post<DbStatus>('/db/docker/teardown', {}),
}
