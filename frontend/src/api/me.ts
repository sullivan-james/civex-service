import { api } from './client'

/** Who is using this project and what they may do (`GET /me`,
 * `domain/permissions.py`). `actions` maps each action to where it may be
 * done: `project` (everywhere) or `collection:<id>` entries. */
export interface Me {
  account: {
    name: string
    kind: 'local' | 'user' | string
    manage_url: string | null
  }
  permissions: {
    actions: Record<string, string[]>
    all: Record<string, string>
  }
}

export const meApi = {
  get: () => api.get<Me>('/me'),
}
