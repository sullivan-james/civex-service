import type { FileLocation } from '../api/files'
import { useUISettings } from './useUISettings'
import { useVolumes } from './useStore'

/** When to show where a file is stored. The rule lives here, once, so every
 * place that shows a file agrees:
 *
 * - a file that can't be opened right now is always shown, with why;
 * - so is one another device added that isn't on this computer yet (opening
 *   it downloads it, which takes a moment), and one added here that isn't on
 *   the server yet (other computers can't open it);
 * - once there is more than one volume, the volume is shown, since it is then
 *   a real question where something is;
 * - in advanced mode it is always shown, with a way to see the details;
 * - otherwise (one volume, nothing wrong) there is nothing to say. */
export function useFileLocationDisplay(
  location: FileLocation | null | undefined,
) {
  const { data: ui } = useUISettings()
  const { data: volumes } = useVolumes()
  const advanced = ui?.show_advanced ?? false
  const multiVolume = (volumes?.length ?? 0) > 1
  const unavailable = location?.available === false
  const show =
    !!location &&
    (unavailable ||
      location.state === 'remote' ||
      location.sent === false ||
      advanced ||
      (multiVolume && location.volume != null))
  return { show, advanced, unavailable }
}
