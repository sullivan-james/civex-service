import { api } from './client'

export interface Collection {
  id: string
  name: string
  description: string | null
  record_count: number
}

export const collectionsApi = {
  list: ()                                                              => api.get<Collection[]>('/collections'),
  get:  (name: string)                                                  => api.get<Collection>(`/collections/${name}`),
  create: (body: { name: string; description?: string })                => api.post<Collection>('/collections', body),
  update: (name: string, body: { rename?: string; description?: string }) =>
    api.patch<Collection>(`/collections/${name}`, body),
  delete: (name: string)                                                => api.delete<void>(`/collections/${name}`),
}
