import type { PlaceKind } from '../api/fileAccess'

/** What a place is called, the same in the Files tab's summary, its filter
 * and each row. */
export function placeLabel(p: { place: string; kind: PlaceKind }): string {
  if (p.kind === 'server') return 'Only on the server'
  if (p.kind === 'missing') return 'Missing'
  if (p.kind === 'unreachable') return `${p.place} (not reachable)`
  return p.place
}
