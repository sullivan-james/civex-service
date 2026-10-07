import type { PlaceKind } from '../../api/fileAccess'
import { PLACE_TONE, placeLabel } from '../../utils/places'
import { STATE_LABEL, STATE_TONE, type VolumeState } from '../../utils/volumes'
import { SegmentBar, Status } from '../ui'

/** A volume's state, as it is shown everywhere: its dot and word, and why
 * (with what to do) in a tooltip. */
export function VolumeStatus({
  state,
  reason,
  fix,
}: {
  state: VolumeState | string
  reason?: string | null
  fix?: string | null
}) {
  const known = state in STATE_LABEL ? (state as VolumeState) : null
  const why = [reason, fix].filter(Boolean).join(' ')
  return (
    <Status tone={known ? STATE_TONE[known] : 'neutral'} why={why || undefined}>
      {known ? STATE_LABEL[known] : state}
    </Status>
  )
}

/** Where a file is, as it is shown everywhere: a drive, a drive that can't be
 * reached, only on the server, or missing. */
export function PlaceStatus({
  place,
  kind,
  reason,
  fix,
}: {
  place: string
  kind: PlaceKind
  reason?: string | null
  fix?: string | null
}) {
  const why = [reason, fix].filter(Boolean).join(' ')
  return (
    <Status tone={PLACE_TONE[kind]} why={why || undefined}>
      {placeLabel({ place, kind })}
    </Status>
  )
}

/** Where files are, as one bar split by place (by bytes; a place with only
 * files whose size isn't known still shows). */
export function PlacesBar({
  places,
  label = 'Where the files are',
}: {
  places: { place: string; kind: PlaceKind; files: number; bytes: number }[]
  label?: string
}) {
  return (
    <SegmentBar
      label={label}
      parts={places.map((p) => ({
        key: `${p.kind}:${p.place}`,
        label: `${placeLabel(p)}: ${p.files.toLocaleString()}`,
        value: Math.max(p.bytes, 1),
        tone: PLACE_TONE[p.kind],
      }))}
    />
  )
}
