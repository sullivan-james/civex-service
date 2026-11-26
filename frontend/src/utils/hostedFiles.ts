import type { FileLocation } from '../api/files'

/** How files are described where a host (a hub) keeps them: there are no
 * drives to name, only whether a file is on the hub. The wording lives here,
 * once, so every place that shows a file agrees. */

export const TEMPORARILY_UNAVAILABLE =
  'Temporarily unavailable. Try again shortly.'

/** The device that added a file, when the server's reason names it
 * ("It was added on 'laptop'."). */
export function addedOn(reason: string | null | undefined): string | null {
  const m = /added on '([^']+)'/.exec(reason ?? '')
  return m ? m[1] : null
}

/** A file still arriving (within the wait for its device to upload it): where
 * the data says which device added it, that device is the one to upload it. */
export function notOnHub(reason?: string | null): string {
  const device = addedOn(reason)
  return device
    ? `Not on the hub yet. It will appear when ‘${device}’ next syncs.`
    : 'Not on the hub yet. It will appear when the device that added it next syncs.'
}

/** A file past the wait: it is missing. */
export function missingOnHub(reason?: string | null): string {
  const device = addedOn(reason)
  return device
    ? `Missing. It was added on ‘${device}’ and never uploaded.`
    : 'Missing. The device that added it never uploaded it.'
}

export type HostedFileState = 'ok' | 'missing' | 'unavailable' | 'arriving'

/** What a hosted file's state comes to: present, not on the hub yet, there
 * but out of reach, or on its way up. */
export function hostedState(
  loc: Pick<FileLocation, 'state' | 'available' | 'volume'> | null | undefined,
): HostedFileState {
  if (!loc) return 'ok'
  if (loc.state === 'arriving') return 'arriving'
  if (loc.state === 'absent' || loc.state === 'remote') return 'missing'
  if (loc.available === false) {
    // On a store that can't be reached right now, or not stored anywhere.
    return loc.volume === null ? 'missing' : 'unavailable'
  }
  return loc.volume === null && loc.available !== true ? 'missing' : 'ok'
}

export const HOSTED_STATE_TEXT: Record<
  Exclude<HostedFileState, 'ok' | 'missing'>,
  string
> = {
  unavailable: TEMPORARILY_UNAVAILABLE,
  arriving:
    'Not on the hub yet. It will appear when the device that added it next syncs.',
}

/** The sentence for a hosted file's state; null when nothing is wrong. */
export function hostedMessage(
  state: HostedFileState,
  reason?: string | null,
): string | null {
  if (state === 'ok') return null
  if (state === 'missing') return missingOnHub(reason)
  return HOSTED_STATE_TEXT[state]
}
