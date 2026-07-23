import { api } from './client'

export interface PluginInfo {
  id: string
  description: string
  builtin: boolean
  filename: string | null
}

export interface PluginSource {
  filename: string
  code: string
}

export const pluginsApi = {
  list: () => api.get<PluginInfo[]>('/plugins'),
  source: (filename: string) =>
    api.get<PluginSource>(`/plugins/${encodeURIComponent(filename)}/source`),
  save: (name: string, code: string) =>
    api.post<{ filename: string }>('/plugins', { name, code }),
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.upload<{ filename: string; plugin_id: string }>(
      '/plugins/upload',
      form,
    )
  },
}
