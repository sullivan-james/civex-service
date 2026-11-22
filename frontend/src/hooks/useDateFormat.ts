import { useSyncExternalStore } from 'react'
import {
  getDateFormat,
  setDateFormat,
  subscribeDateFormat,
  type DateFormat,
} from '../utils/dateFormat'

export { setDateFormat }

/** The date pattern chosen in Settings → Appearance (`utils/dateFormat`).
 * `App` reads it, so choosing another re-renders every page at once; a
 * component needs it only to show the pattern itself. */
export function useDateFormat(): DateFormat {
  return useSyncExternalStore(subscribeDateFormat, getDateFormat)
}
