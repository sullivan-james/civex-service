import { useCallback, useEffect, useRef, useState } from 'react'
import { useToast } from '../components/ui/ToastProvider'
import { syncNotice } from '../utils/syncToast'
import { useRemoteStatus, useSyncNow } from './useRemote'

/** Shown as spinning for at least this long, so a sync that finishes at once
 * still visibly happens. */
const MIN_SPIN_MS = 700
/** Give up waiting for an answer after this long. */
const GIVE_UP_MS = 60_000

interface Asked {
  synced: string | null
  errorAt: string | null
  at: number
}

/** The top-bar sync button's behaviour: pressing it asks for a sync and `spinning`
 * stays true until that sync has finished (a good result is answered by a toast;
 * a failure or values to review are the status bar's, see `syncNotice`); syncs
 * that run by themselves are told only when they did something. */
export function useManualSync() {
  const { data } = useRemoteStatus()
  const syncNow = useSyncNow()
  const toast = useToast()
  const [asked, setAsked] = useState<Asked | null>(null)
  const seen = useRef<typeof data | null>(null)

  const tell = useCallback(
    (notice: ReturnType<typeof syncNotice>) => {
      if (notice) toast.success(notice.message)
    },
    [toast],
  )

  const answered =
    asked !== null &&
    !!data &&
    (data.last_synced_at !== asked.synced ||
      data.last_error_at !== asked.errorAt)

  // A sync that ran by itself: tell it only if it did something or went wrong.
  useEffect(() => {
    if (!data?.configured) {
      seen.current = null
      return
    }
    if (!asked) tell(syncNotice(seen.current ?? null, data, false))
    seen.current = data
  }, [data, asked, tell])

  // The sync that was asked for has finished: answer it, after it has spun long
  // enough to be seen.
  useEffect(() => {
    if (!asked || !answered || !data) return
    const timer = setTimeout(
      () => {
        tell(syncNotice({ last_synced_at: asked.synced }, data, true))
        setAsked(null)
      },
      Math.max(0, asked.at + MIN_SPIN_MS - Date.now()),
    )
    return () => clearTimeout(timer)
  }, [asked, answered, data, tell])

  useEffect(() => {
    if (!asked) return
    const timer = setTimeout(() => setAsked(null), GIVE_UP_MS)
    return () => clearTimeout(timer)
  }, [asked])

  const request = useCallback(
    (after?: () => void) => {
      setAsked({
        synced: data?.last_synced_at ?? null,
        errorAt: data?.last_error_at ?? null,
        at: Date.now(),
      })
      syncNow.mutate(undefined, { onSettled: after })
    },
    [data, syncNow],
  )

  return { request, spinning: asked !== null || syncNow.isPending }
}
