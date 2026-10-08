import { useSyncExternalStore } from 'react'
import { updatesApi, type StartUpdate } from '../api/updates'
import { errorMessage } from '../lib/errors'

/** Where an update started from the app has got to. It lives outside any
 * component (like file jobs), so the Updates page and the status bar show the
 * same thing and it survives moving between pages.
 *
 * `closing`: civex was asked to update and is about to close.
 * `restarting`: it has closed; the update runs, then civex starts again, and
 *   the page reloads as soon as it answers.
 * `timeout`: it hasn't come back. `failed`: it refused to start (`message`). */
export type RestartPhase =
  | { kind: 'idle' }
  | { kind: 'closing' }
  | { kind: 'restarting' }
  | { kind: 'timeout' }
  | { kind: 'failed'; message: string }

const POLL_MS = 1000
/** First starts after an update can be slow (uv fetches packages). */
const GIVE_UP_MS = 10 * 60 * 1000

let phase: RestartPhase = { kind: 'idle' }
const listeners = new Set<() => void>()

function set(next: RestartPhase) {
  phase = next
  listeners.forEach((l) => l())
}

export function useRestartPhase(): RestartPhase {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => {
        listeners.delete(l)
      }
    },
    () => phase,
  )
}

export function clearRestartProblem() {
  if (phase.kind === 'failed' || phase.kind === 'timeout') set({ kind: 'idle' })
}

async function answers(): Promise<boolean> {
  try {
    return (await fetch('/health', { cache: 'no-store' })).ok
  } catch {
    return false
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** Ask civex to update and start again, then reload once it is back. It must
 * be seen going away first: for a moment after answering it still does. */
export async function restartForUpdate(start: StartUpdate): Promise<void> {
  if (phase.kind === 'closing' || phase.kind === 'restarting') return
  set({ kind: 'closing' })
  try {
    await updatesApi.start(start)
  } catch (e) {
    set({ kind: 'failed', message: errorMessage(e) })
    return
  }
  const deadline = Date.now() + GIVE_UP_MS
  let wentAway = false
  while (Date.now() < deadline) {
    await sleep(POLL_MS)
    if (!(await answers())) {
      if (!wentAway) set({ kind: 'restarting' })
      wentAway = true
    } else if (wentAway) {
      window.location.reload()
      return
    }
  }
  set({ kind: 'timeout' })
}
