import type { PlaceKind } from '../api/fileAccess'
import type { Tone } from '../components/ui'

/** What a place is called, the same in the Files tab's summary, its filter
 * and each row. */
export function placeLabel(p: { place: string; kind: PlaceKind }): string {
  // Not here, and not checked with the server (a download says if it lacks it).
  if (p.kind === 'server') return 'Not on this computer'
  if (p.kind === 'missing') return 'Missing'
  if (p.kind === 'unreachable') return `${p.place} (not reachable)`
  return p.place
}

/** How many files are in a place, as part of a sentence: "60 on SecondVolume",
 * "25 not on this computer", "2 on test1, which can't be reached", "1 missing". */
export function placeCount(p: {
  place: string
  kind: PlaceKind
  files: number
}): string {
  const n = p.files.toLocaleString()
  if (p.kind === 'server') return `${n} not on this computer`
  if (p.kind === 'missing') return `${n} missing`
  if (p.kind === 'unreachable')
    return `${n} on ${p.place}, which can't be reached`
  return `${n} on ${p.place}`
}

/** The colour of a place, everywhere it is shown: on a drive here is fine, a
 * drive that can't be reached is worth a look, only on the server is simply
 * not here, missing is wrong. */
export const PLACE_TONE: Record<PlaceKind, Tone> = {
  drive: 'ok',
  unreachable: 'attention',
  server: 'neutral',
  missing: 'danger',
}
