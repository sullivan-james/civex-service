import { useState, type KeyboardEvent, type ReactNode } from 'react'
import { IconButton } from './IconButton'
import { ChevronDown, ChevronUp, GripVertical } from './icons'

export interface SortableListProps<T> {
  items: T[]
  getKey: (item: T) => string
  /** Plain-text name of an item, used for the move buttons and the screen
   * reader announcement. */
  getLabel: (item: T) => string
  /** Called with the new order (not a diff). The parent persists it. */
  onReorder: (next: T[], moved: T, toIndex: number) => void
  renderItem: (item: T, index: number) => ReactNode
  /** Up/down buttons are for touch and precise nudging; show them on every row
   * (`always`), only the rows `showMoveButtons` picks, or never. */
  moveButtons?: 'always' | 'never' | ((item: T) => boolean)
  disabled?: boolean
  /** Accessible name for the list. */
  label: string
  className?: string
  /** Per-row class, e.g. to highlight the selected row. */
  rowClassName?: (item: T) => string
}

/** The one reorderable list: drag by the grip or the row, Alt/Cmd+Arrow on a
 * focused row, or the move buttons. Announces every move to screen readers. */
export function SortableList<T>({
  items,
  getKey,
  getLabel,
  onReorder,
  renderItem,
  moveButtons = 'never',
  disabled = false,
  label,
  className = '',
  rowClassName,
}: SortableListProps<T>) {
  const [dragFrom, setDragFrom] = useState<number | null>(null)
  const [dragOver, setDragOver] = useState<number | null>(null)
  const [announcement, setAnnouncement] = useState('')

  function move(from: number, to: number) {
    if (disabled || to < 0 || to >= items.length || from === to) return
    const next = [...items]
    const [moved] = next.splice(from, 1)
    next.splice(to, 0, moved)
    onReorder(next, moved, to)
    setAnnouncement(
      `${getLabel(moved)} moved to position ${to + 1} of ${next.length}.`,
    )
  }

  function onKeyDown(e: KeyboardEvent, index: number) {
    if (!(e.altKey || e.metaKey)) return
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      move(index, index - 1)
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      move(index, index + 1)
    }
  }

  function endDrag() {
    setDragFrom(null)
    setDragOver(null)
  }

  const showButtons = (item: T) =>
    moveButtons === 'always' ||
    (typeof moveButtons === 'function' && moveButtons(item))

  return (
    <>
      <ul aria-label={label} className={`divide-y divide-border ${className}`}>
        {items.map((item, index) => (
          <li
            key={getKey(item)}
            draggable={!disabled}
            onKeyDown={(e) => onKeyDown(e, index)}
            onDragStart={() => setDragFrom(index)}
            onDragEnd={endDrag}
            onDragOver={(e) => {
              if (dragFrom === null) return
              e.preventDefault()
              setDragOver(index)
            }}
            onDrop={() => {
              if (dragFrom !== null) move(dragFrom, index)
              endDrag()
            }}
            className={`flex items-stretch ${rowClassName?.(item) ?? ''} ${
              dragOver === index && dragFrom !== index
                ? 'bg-accent-subtle'
                : dragFrom === index
                  ? 'opacity-50'
                  : ''
            }`}
          >
            {!disabled && (
              <span
                aria-hidden="true"
                className="flex w-8 shrink-0 cursor-grab items-center justify-center text-fg-subtle hover:text-fg-muted active:cursor-grabbing"
              >
                <GripVertical size={16} />
              </span>
            )}
            <div className="min-w-0 flex-1">{renderItem(item, index)}</div>
            {showButtons(item) && (
              <span className="flex shrink-0 items-center pr-1">
                <IconButton
                  icon={ChevronUp}
                  aria-label={`Move ${getLabel(item)} up`}
                  variant="subtle"
                  disabled={disabled || index === 0}
                  onClick={() => move(index, index - 1)}
                />
                <IconButton
                  icon={ChevronDown}
                  aria-label={`Move ${getLabel(item)} down`}
                  variant="subtle"
                  disabled={disabled || index === items.length - 1}
                  onClick={() => move(index, index + 1)}
                />
              </span>
            )}
          </li>
        ))}
      </ul>
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>
    </>
  )
}
