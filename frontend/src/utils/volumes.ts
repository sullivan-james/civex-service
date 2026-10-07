import type { VolumeStats } from '../api/store'
import type { Tone } from '../components/ui'

export type VolumeState = VolumeStats['state']

export const STATE_LABEL: Record<VolumeState, string> = {
  online: 'Online',
  offline: 'Offline',
  wrong_drive: 'Wrong drive',
  readonly: 'Read-only',
  retired: 'Retired',
}

/** The colour of a volume's state, everywhere it is shown. */
export const STATE_TONE: Record<VolumeState, Tone> = {
  online: 'ok',
  offline: 'attention',
  readonly: 'attention',
  wrong_drive: 'danger',
  retired: 'neutral',
}

/** States where the volume's files can't be reached or it needs a decision. */
export const NEEDS_ATTENTION: ReadonlyArray<VolumeState> = [
  'offline',
  'wrong_drive',
]
