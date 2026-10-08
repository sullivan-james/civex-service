import { useSyncExternalStore } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { updatesApi } from '../api/updates'

/** Per-browser conveniences about updates, in localStorage: whether to look
 * for pre-releases, and which available version was put off ("Later"). None
 * of it must persist reliably: losing it only shows a notice again. (An
 * update's outcome is dismissed on the server: `useDismissLastUpdate`.) */
const KEYS = {
  pre: 'civex.update.pre',
  later: 'civex.update.later',
} as const
type Key = keyof typeof KEYS

const CHANGE_EVENT = 'civex-update-prefs'

function read(key: Key): string | null {
  try {
    return localStorage.getItem(KEYS[key])
  } catch {
    return null
  }
}

export function writeUpdatePref(key: Key, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(KEYS[key])
    else localStorage.setItem(KEYS[key], value)
  } catch {
    // Private window or blocked storage: the choice lasts this page only.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT))
}

function subscribe(onChange: () => void) {
  window.addEventListener(CHANGE_EVENT, onChange)
  window.addEventListener('storage', onChange)
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange)
    window.removeEventListener('storage', onChange)
  }
}

export function useUpdatePref(key: Key): string | null {
  return useSyncExternalStore(subscribe, () => read(key))
}

export function usePreReleases(): [boolean, (on: boolean) => void] {
  const on = useUpdatePref('pre') === '1'
  return [on, (next) => writeUpdatePref('pre', next ? '1' : null)]
}

/** Whether a newer civex is on PyPI (asked through the server, which also
 * says whether it can install it). Asked once a session, not on every page. */
export function useUpdateStatus(pre: boolean) {
  return useQuery({
    queryKey: ['update', pre],
    queryFn: () => updatesApi.status(pre),
    staleTime: 6 * 60 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
  })
}

/** Forget the last update's outcome, for every page and the next opening of
 * the app alike (it is kept by the server, not this browser). */
export function useDismissLastUpdate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: updatesApi.dismissLast,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['update'] }),
  })
}
