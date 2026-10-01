import { useCallback, useMemo, useSyncExternalStore } from 'react'
import {
  PINS_KEY,
  RECENTS_KEY,
  parseTargets,
  pushRecent,
  togglePin,
  type NavTarget,
} from '../utils/pins'

const CHANGE_EVENT = 'civex:nav-targets-changed'

function subscribe(onChange: () => void) {
  window.addEventListener(CHANGE_EVENT, onChange)
  window.addEventListener('storage', onChange)
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange)
    window.removeEventListener('storage', onChange)
  }
}

function snapshot(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

/** The stored list, refreshed when it changes here or in another tab. The
 * raw string is the snapshot (stable between changes); parsing is memoised
 * on it. */
function useStoredTargets(key: string): NavTarget[] {
  const raw = useSyncExternalStore(
    subscribe,
    () => snapshot(key),
    () => null,
  )
  return useMemo(() => parseTargets(raw), [raw])
}

function notify() {
  window.dispatchEvent(new Event(CHANGE_EVENT))
}

/** Records that `target` was just opened, for "pick up where you left off". */
export function recordRecent(target: NavTarget) {
  try {
    pushRecent(localStorage, target)
    notify()
  } catch {
    /* no storage: nothing is remembered */
  }
}

export function usePins() {
  const pins = useStoredTargets(PINS_KEY)
  const toggle = useCallback((target: NavTarget) => {
    try {
      togglePin(localStorage, target)
      notify()
    } catch {
      /* no storage: the pin can't be kept */
    }
  }, [])
  const isPinned = useCallback(
    (key: string) => pins.some((p) => p.key === key),
    [pins],
  )
  return { pins, toggle, isPinned }
}

export function useRecents(): NavTarget[] {
  return useStoredTargets(RECENTS_KEY)
}
