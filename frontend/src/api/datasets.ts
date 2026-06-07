import { api } from './client'

export interface Dataset {
  id: string
  name: string
  description: string | null
  record_count: number
}

export const datasetsApi = {
  list: ()                                                          => api.get<Dataset[]>('/datasets'),
  get:  (name: string)                                              => api.get<Dataset>(`/datasets/${name}`),
  create: (body: { name: string; description?: string })            => api.post<Dataset>('/datasets', body),
  update: (name: string, body: { rename?: string; description?: string }) =>
    api.patch<Dataset>(`/datasets/${name}`, body),
  delete: (name: string)                                            => api.delete<void>(`/datasets/${name}`),
}
