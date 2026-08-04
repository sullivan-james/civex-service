import { api } from './client'

export interface PluginIOSpec {
  name: string
  type: string
  required: boolean
  description: string
}

export interface PluginInfo {
  id: string
  name: string
  description: string
  builtin: boolean
  category: string
  capabilities: string[]
  // null = plugin declared no contract in this direction; [] = it declared
  // it has none (see civex_plugin_sdk.PluginBase.inputs)
  inputs: PluginIOSpec[] | null
  outputs: PluginIOSpec[] | null
  config_schema: {
    properties?: Record<
      string,
      { type?: string; default?: unknown; description?: string }
    >
    required?: string[]
  }
  filename: string | null
}

export interface PluginSource {
  filename: string
  code: string
}

export interface PluginLoadError {
  filename: string
  error: string
}

export const pluginsApi = {
  list: () => api.get<PluginInfo[]>('/plugins'),
  loadErrors: () => api.get<PluginLoadError[]>('/plugins/errors'),
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
  delete: (filename: string, force = false) =>
    api.delete<void>(
      `/plugins/${encodeURIComponent(filename)}${force ? '?force=true' : ''}`,
    ),
}
