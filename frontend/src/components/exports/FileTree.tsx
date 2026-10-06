import { useState } from 'react'
import { visibleRows, type TreeRow } from '../../utils/fileTree'
import { formatSize } from '../../utils/storage'
import { ChevronDown, ChevronRight, FileText, Folder, Table } from '../ui/icons'

/** A folder tree: folders and files with icons, indented by level. With
 * `collapsible`, a folder opens and closes on click and says how many files it
 * holds; otherwise it is a picture of a structure. The one tree drawn anywhere
 * in the app, for layout examples and for the real preview of an export. */
export function FileTree({
  rows,
  label,
  collapsible = false,
  className = '',
}: {
  rows: TreeRow[]
  label: string
  collapsible?: boolean
  className?: string
}) {
  const [collapsed, setCollapsed] = useState<ReadonlySet<number>>(new Set())
  const toggle = (index: number) =>
    setCollapsed((c) => {
      const next = new Set(c)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })

  return (
    <ul aria-label={label} className={`space-y-0.5 text-sm ${className}`}>
      {visibleRows(rows, collapsible ? collapsed : new Set()).map(
        ({ row, index }) => (
          <li key={index} style={{ paddingLeft: `${row.depth * 20}px` }}>
            {row.kind === 'folder' ? (
              <FolderRow
                row={row}
                open={!collapsed.has(index)}
                onToggle={collapsible ? () => toggle(index) : undefined}
              />
            ) : row.kind === 'table' ? (
              <TableRow row={row} />
            ) : (
              <FileRow row={row} />
            )}
          </li>
        ),
      )}
    </ul>
  )
}

function FolderRow({
  row,
  open,
  onToggle,
}: {
  row: TreeRow
  open: boolean
  onToggle?: () => void
}) {
  const content = (
    <>
      {onToggle &&
        (open ? (
          <ChevronDown
            size={14}
            className="shrink-0 text-fg-subtle"
            aria-hidden="true"
          />
        ) : (
          <ChevronRight
            size={14}
            className="shrink-0 text-fg-subtle"
            aria-hidden="true"
          />
        ))}
      <Folder size={16} className="shrink-0 text-accent" aria-hidden="true" />
      <span className="truncate font-medium text-fg">{row.name}</span>
      {row.count !== undefined && onToggle && (
        <span className="ml-1 text-xs text-fg-muted">
          {row.count.toLocaleString()}
        </span>
      )}
    </>
  )
  if (!onToggle)
    return <div className="flex items-center gap-1.5 py-0.5">{content}</div>
  return (
    <button
      type="button"
      aria-expanded={open}
      onClick={onToggle}
      className="flex w-full cursor-pointer items-center gap-1.5 rounded px-1 py-0.5 text-left hover:bg-canvas-inset focus-visible:outline-2 focus-visible:outline-accent"
    >
      {content}
    </button>
  )
}

/** A table the export writes, in the folder it will be in. Told apart from a
 * stored file by its icon and by saying how many rows it has. */
function TableRow({ row }: { row: TreeRow }) {
  return (
    <div className="flex items-center gap-1.5 py-0.5">
      <Table size={16} className="shrink-0 text-accent" aria-hidden="true" />
      <span className="truncate font-medium text-fg">{row.name}</span>
      <span className="ml-auto pl-3 text-xs text-fg-subtle">
        {(row.rows ?? 0).toLocaleString()} {row.rows === 1 ? 'row' : 'rows'}
      </span>
    </div>
  )
}

function FileRow({ row }: { row: TreeRow }) {
  const gone = row.available === false
  return (
    <div
      className={`flex items-center gap-1.5 py-0.5 ${gone ? 'text-fg-muted line-through' : 'text-fg-muted'}`}
      title={gone ? 'Can’t be reached right now' : undefined}
    >
      <FileText
        size={16}
        className="shrink-0 text-fg-subtle"
        aria-hidden="true"
      />
      <span className={`truncate ${gone ? '' : 'text-fg'}`}>{row.name}</span>
      {row.size !== undefined && (
        <span className="ml-auto pl-3 text-xs text-fg-subtle">
          {formatSize(row.size)}
        </span>
      )}
    </div>
  )
}
