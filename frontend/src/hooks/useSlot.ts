import { useSyncExternalStore } from 'react'
import {
  slotEntries,
  subscribe,
  type SlotEntry,
  type SlotName,
} from '../utils/slots'

/** What a host's extensions registered in `name` (`utils/slots`), kept
 * current as they register. */
export function useSlot(name: SlotName): readonly SlotEntry[] {
  return useSyncExternalStore(
    subscribe,
    () => slotEntries(name),
    () => slotEntries(name),
  )
}
