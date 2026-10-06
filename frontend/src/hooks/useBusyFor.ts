import { useEffect, useState } from 'react'

/** True once `busy` has stayed true for `ms` without a break. How things that are
 * usually over in a moment avoid flashing in the status bar. */
export function useBusyFor(busy: boolean, ms: number): boolean {
  const [long, setLong] = useState(false)
  useEffect(() => {
    if (!busy) return
    const timer = setTimeout(() => setLong(true), ms)
    return () => {
      clearTimeout(timer)
      setLong(false)
    }
  }, [busy, ms])
  return long
}
