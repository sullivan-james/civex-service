import type { ComponentType } from 'react'
import { ListFilter, Upload } from '../components/ui/icons'

/** What a saved thing is called wherever saved things are listed (the
 * saved-filters bar, pins, Ctrl+K): a **Saved filter** (which records:
 * filter, search, sort) or an **Export** (an export definition: files and
 * tables). The one place that decides the word and the icon. */
export type SavedKind = 'filter' | 'export'

type IconType = ComponentType<{
  size?: number
  className?: string
  'aria-hidden'?: boolean | 'true'
}>

export const SAVED_KINDS: Record<SavedKind, { word: string; icon: IconType }> =
  {
    filter: { word: 'Saved filter', icon: ListFilter },
    export: { word: 'Export', icon: Upload },
  }

/** The kind a pin kept in the browser names: one saved before filters were
 * called that reads as a saved filter. */
export function savedKind(saved: string | undefined): SavedKind | undefined {
  if (!saved) return undefined
  return saved === 'export' ? 'export' : 'filter'
}
