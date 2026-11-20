import type { ComponentType } from 'react'
import type { View } from '../api/views'
import { BarChart3, ListFilter, Upload } from '../components/ui/icons'

/** What a saved thing gives you, which is what it is called wherever saved
 * things are listed (the saved-views bar, pins, Ctrl+K): a **List** (a saved
 * view: records, filtered and sorted), an **Analysis** (a saved view with a
 * summary: counts and averages by group) or an **Export** (an export
 * definition: files and tables). The one place that decides the word and the
 * icon. */
export type SavedKind = 'list' | 'analysis' | 'export'

type IconType = ComponentType<{
  size?: number
  className?: string
  'aria-hidden'?: boolean | 'true'
}>

export const SAVED_KINDS: Record<
  SavedKind,
  { word: string; icon: IconType; hint: string }
> = {
  list: {
    word: 'List',
    icon: ListFilter,
    hint: 'A saved list: records, filtered and sorted.',
  },
  analysis: {
    word: 'Analysis',
    icon: BarChart3,
    hint: 'A saved analysis: the records counted and measured by group.',
  },
  export: {
    word: 'Export',
    icon: Upload,
    hint: 'A saved export: files and tables, made in one go.',
  },
}

/** A saved view is an analysis when it carries a summary, else a list. */
export function viewKind(view: Pick<View, 'summary'>): SavedKind {
  return view.summary ? 'analysis' : 'list'
}
