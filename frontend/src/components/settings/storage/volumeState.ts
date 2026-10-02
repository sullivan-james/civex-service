import type { VolumeStats } from '../../../api/store'

export const STATE_LABEL: Record<VolumeStats['state'], string> = {
  online: 'Online',
  offline: 'Offline',
  wrong_drive: 'Wrong drive',
  readonly: 'Read-only',
  retired: 'Retired',
}

/** States where the volume's files can't be reached or it needs a decision. */
export const NEEDS_ATTENTION: ReadonlyArray<VolumeStats['state']> = [
  'offline',
  'wrong_drive',
]
