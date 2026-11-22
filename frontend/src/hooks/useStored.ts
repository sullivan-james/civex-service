import { useCallback, useState } from 'react'
import { projectKey } from '../utils/host'

/** Read such a choice once, outside a component (a flow that runs later). */
export function readStored<T>(key: string, initial: T): T {
  try {
    const raw = localStorage.getItem(projectKey(key))
    return raw === null ? initial : (JSON.parse(raw) as T)
  } catch {
    return initial
  }
}

/** A small choice kept in this browser for this project (a panel's width,
 * whether it is folded): read once, written on every change. */
export function useStored<T>(key: string, initial: T): [T, (next: T) => void] {
  const name = projectKey(key)
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(name)
      return raw === null ? initial : (JSON.parse(raw) as T)
    } catch {
      return initial
    }
  })
  const set = useCallback(
    (next: T) => {
      setValue(next)
      try {
        localStorage.setItem(name, JSON.stringify(next))
      } catch {
        // Storage refused (private mode): the choice lasts for this visit.
      }
    },
    [name],
  )
  return [value, set]
}
