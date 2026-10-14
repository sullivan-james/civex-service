import { api } from './client'

/** What this server does for this project, by name (`domain/features.py`),
 * and every feature a civex server may offer with what it means. */
export interface Features {
  features: string[]
  all: Record<string, string>
}

export const featuresApi = {
  get: () => api.get<Features>('/status/features'),
}
