import type { VolumeStats } from '../../../api/store'

const COLOUR: Record<VolumeStats['state'], string> = {
  online: 'bg-success',
  offline: 'bg-fg-subtle',
  wrong_drive: 'bg-danger',
  readonly: 'bg-attention',
  retired: 'bg-fg-subtle',
}

/** A small coloured dot. Decorative: the state is always also written out. */
export function StatusDot({ state }: { state: VolumeStats['state'] }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block h-2 w-2 shrink-0 rounded-full ${COLOUR[state]}`}
    />
  )
}
