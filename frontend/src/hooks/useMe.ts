import { useQuery } from '@tanstack/react-query'
import { meApi, type Me } from '../api/me'
import {
  ACTIONS,
  EVERYTHING,
  can,
  notAllowed,
  type Action,
  type Allowed,
} from '../utils/permissions'

/** Who is using this project and what they may do (`GET /me`), asked once.
 * Until the server has answered, the local user and everything are assumed,
 * so a page built for one person's machine doesn't flicker. */
export function useMe(): Me | undefined {
  const { data } = useQuery({
    queryKey: ['me'],
    queryFn: meApi.get,
    staleTime: Infinity,
  })
  return data?.permissions?.actions ? data : undefined
}

export function useAccount(): Me['account'] {
  return useMe()?.account ?? { name: 'you', kind: 'local', manage_url: null }
}

/** `can('write_records', collectionId)` and the sentence to show when not:
 * the one way a control learns what this person may do. */
export function usePermissions(): {
  can: (action: Action, collectionId?: string | null) => boolean
  why: (action: Action) => string
} {
  const me = useMe()
  const allowed: Allowed = me?.permissions.actions ?? EVERYTHING
  const words = { ...ACTIONS, ...(me?.permissions.all ?? {}) }
  return {
    can: (action, collectionId) => can(allowed, action, collectionId),
    why: (action) => notAllowed(action, words),
  }
}
