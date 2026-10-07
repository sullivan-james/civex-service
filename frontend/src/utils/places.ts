import type { PlaceKind } from '../api/fileAccess'

/** What a place is called, the same in the Files tab's summary, its filter
 * and each row. */
export function placeLabel(p: { place: string; kind: PlaceKind }): string {
  // Not here, and not checked with the server (a download says if it lacks it).
  if (p.kind === 'server') return 'Not on this computer'
  if (p.kind === 'missing') return 'Missing'
  if (p.kind === 'unreachable') return `${p.place} (not reachable)`
  return p.place
}
