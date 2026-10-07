import { useTransfers } from './useTransfers'
import { useVolumes } from './useStore'
import { NEEDS_ATTENTION } from '../utils/volumes'

export type StorageTab = 'volumes' | 'collections' | 'tasks'

export interface AttentionItem {
  key: string
  tone: 'danger' | 'attention' | 'info'
  text: string
  /** Where on the Storage page to deal with it. */
  tab: StorageTab
}

/** Everything about storage that wants a person's eye, in one list: the single
 * place that decides what counts. Empty when all is well. */
export function useStorageAttention(): AttentionItem[] {
  const { data: volumes = [] } = useVolumes()
  const { data: transfers = [] } = useTransfers()
  const items: AttentionItem[] = []

  for (const v of volumes) {
    // An unreachable volume that holds nothing isn't worth a banner.
    const holdsFiles = v.civex_used_bytes === null || v.civex_used_bytes > 0
    if (NEEDS_ATTENTION.includes(v.state) && holdsFiles)
      items.push({
        key: `volume-${v.name}`,
        tone: v.state === 'wrong_drive' ? 'danger' : 'attention',
        text: `${v.name}: ${v.reason || 'not available'}`,
        tab: 'volumes',
      })
    else if (v.available && v.warning)
      items.push({
        key: `space-${v.name}`,
        tone: 'attention',
        text: `${v.name} is running low on space. You can move files off it.`,
        tab: 'volumes',
      })
  }

  const waiting = transfers.filter((t) => t.status === 'queued').length
  if (waiting > 0)
    items.push({
      key: 'moves-waiting',
      tone: 'info',
      text: `${waiting} move${waiting === 1 ? ' is' : 's are'} waiting for the current one to finish.`,
      tab: 'tasks',
    })

  for (const t of transfers) {
    const p = t.progress
    if (t.status === 'running')
      items.push({
        key: `move-${t.id}`,
        tone: 'info',
        text: `Moving files: ${p.files_done} of ${p.files_total} done.`,
        tab: 'tasks',
      })
    else if (t.status === 'paused' || t.status === 'interrupted')
      items.push({
        key: `move-${t.id}`,
        tone: 'attention',
        text:
          t.status === 'interrupted'
            ? 'A move was interrupted. Nothing was lost; it can be resumed.'
            : `A move is paused${t.pause_reason ? `: ${t.pause_reason}` : '.'}`,
        tab: 'tasks',
      })
  }
  return items
}
