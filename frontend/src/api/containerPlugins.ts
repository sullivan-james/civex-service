import { api } from './client'

export interface ContainerPluginInfo {
  name: string
  files: string[]
}

export interface ContainerPluginDetail {
  name: string
  files: Record<string, string>
}

export interface BuildResult {
  success: boolean
  log: string
}

export const containerPluginsApi = {
  list: () => api.get<ContainerPluginInfo[]>('/plugins/containers'),
  get: (name: string) =>
    api.get<ContainerPluginDetail>(
      `/plugins/containers/${encodeURIComponent(name)}`,
    ),
  saveFile: (name: string, path: string, content: string) =>
    api.put<BuildResult>(`/plugins/containers/${encodeURIComponent(name)}`, {
      path,
      content,
    }),
}
