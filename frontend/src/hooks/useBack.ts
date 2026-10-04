import { useCallback } from 'react'
import { useLocation, useNavigate } from 'react-router'

/** "Go back to where I came from": a step back in history when this app put
 * the person here (so the list they left comes back with its filters, tab and
 * scroll), otherwise `fallback` (a link opened in a new tab has nothing
 * behind it). Use it for Cancel, never a hard-coded list address. */
export function useBack(fallback: string) {
  const navigate = useNavigate()
  // The first entry of a session has the key 'default'; any other entry was
  // reached by navigating inside the app, so there is somewhere to go back to.
  const hasHistory = useLocation().key !== 'default'
  return useCallback(() => {
    if (hasHistory) void navigate(-1)
    else void navigate(fallback)
  }, [navigate, hasHistory, fallback])
}
