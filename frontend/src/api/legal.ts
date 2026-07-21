import { api } from './client'

export interface Policy {
  stem: string
  title: string
  content: string
}

export const legalApi = {
  getLicense: () => api.get<{ text: string }>('/legal/license'),
  listPolicies: () => api.get<Policy[]>('/legal/policies'),
  getPolicy: (stem: string) =>
    api.get<Policy>(`/legal/policies/${encodeURIComponent(stem)}`),
}
