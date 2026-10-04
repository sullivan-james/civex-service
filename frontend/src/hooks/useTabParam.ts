import { useCallback } from 'react'
import { useSearchParams } from 'react-router'

/** Keeps the selected tab in the address (`?tab=`) so it can be linked to and
 * survives reload. The default tab leaves the address clean and any other
 * query parameters are kept. */
export function useTabParam<T extends string>(
  tabs: readonly { id: T }[],
  defaultTab: T,
  key = 'tab',
): [T, (next: T) => void] {
  const [params, setParams] = useSearchParams()
  const raw = params.get(key)
  const value = tabs.find((t) => t.id === raw)?.id ?? defaultTab
  const set = useCallback(
    (next: T) =>
      setParams(
        (prev) => {
          const out = new URLSearchParams(prev)
          if (next === defaultTab) out.delete(key)
          else out.set(key, next)
          return out
        },
        // A tab is a place of its own: Back returns to the previous tab.
      ),
    [setParams, defaultTab, key],
  )
  return [value, set]
}
