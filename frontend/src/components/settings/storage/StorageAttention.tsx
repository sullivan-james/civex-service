import {
  useStorageAttention,
  type StorageTab,
} from '../../../hooks/useStorageAttention'
import { AlertTriangle } from '../../ui/icons'

const TONE = {
  danger: 'border-danger-subtle-border bg-danger-subtle text-danger',
  attention: 'border-border bg-canvas-subtle text-attention',
  info: 'border-border bg-canvas-subtle text-fg-muted',
} as const

const TAB_LABEL: Record<StorageTab, string> = {
  volumes: 'Volumes',
  collections: 'Collections',
  tasks: 'Tasks',
}

/** What needs a look, above whichever tab is open, each with a way to it. Shown
 * only when there is something to say. */
export function StorageAttention({
  onGo,
}: {
  onGo: (tab: StorageTab) => void
}) {
  const items = useStorageAttention()
  if (items.length === 0) return null
  return (
    <ul aria-label="Needs attention" className="space-y-2">
      {items.map((item) => (
        <li
          key={item.key}
          className={`flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm ${TONE[item.tone]}`}
        >
          <span className="flex items-start gap-2">
            {item.tone !== 'info' && (
              <AlertTriangle
                size={14}
                className="mt-0.5 shrink-0"
                aria-hidden="true"
              />
            )}
            {item.text}
          </span>
          <button
            type="button"
            onClick={() => onGo(item.tab)}
            className="shrink-0 cursor-pointer text-accent hover:underline"
          >
            Open {TAB_LABEL[item.tab]}
          </button>
        </li>
      ))}
    </ul>
  )
}
