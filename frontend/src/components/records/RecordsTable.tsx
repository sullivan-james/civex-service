import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { DataTable, Badge, type DataTableColumn } from '../ui'
import { displayLabel } from '../../utils/naming'
import { formatDate } from '../../lib/utils'
import { ReferenceLink } from './ReferenceLink'
import { FileCell } from './FileCell'
import { fileRefsIn } from '../../utils/fileRefs'
import type { Schema } from '../../api/schemas'
import { openNotesText } from '../../utils/notes'

export interface RecordsTableColumn {
  name: string
  label: string
  /** Field type, for reference/reference_list values to render as links
   * instead of raw ids. Omit for projected/preview columns without one. */
  type?: string
  /** Set false for a column the server can't order by (e.g. a join). */
  sortable?: boolean
}

export interface RecordsTableRow {
  id: string
  data: Record<string, unknown>
  natural_name?: string | null
  schema_name?: string
  created_at?: string
  updated_at?: string
  /** The collection it is in (by name). */
  collection?: string | null
  reference_labels?: Record<string, string | null> | null
  reference_collections?: Record<string, string> | null
  child_counts?: Record<string, number> | null
  open_notes?: number | null
  latest_note?: string | null
}

export interface RecordsTableSort {
  key: string
  direction: 'asc' | 'desc'
}

export interface RecordsTableSelection {
  selected: Set<string>
  onToggle: (id: string) => void
  onToggleAll: () => void
  /** A shift-click range as one update, when given (see `useRangeSelect`). */
  onSetMany?: (ids: string[], on: boolean) => void
}

export interface RecordsTableProps {
  columns: RecordsTableColumn[]
  rows: RecordsTableRow[]
  /** Resolves schema badges — only used when `showSchemaColumn` is true. */
  schemas?: Schema[]
  showSchemaColumn?: boolean
  showIdColumn?: boolean
  /** What the first column (the record's name, else its id) is headed. */
  idHeader?: string
  showAddedColumn?: boolean
  /** Renders the ID cell as a link when provided; plain text otherwise. */
  recordLink?: (row: RecordsTableRow) => string
  selection?: RecordsTableSelection
  sort?: RecordsTableSort
  onSortChange?: (columnName: string) => void
  /** An extra last column -- e.g. links down to a row's children. */
  trailing?: { header: string; render: (row: RecordsTableRow) => ReactNode }
  /** A last row about every record listed, not just this page: what the
   * first column says ("All 240") and a cell per column name. */
  totals?: { label: string; cells: Record<string, string> }
}

function formatCellValue(value: unknown): string {
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function Dash() {
  return <span className="text-fg-subtle">—</span>
}

function CellValue({
  col,
  row,
  schemas,
}: {
  col: RecordsTableColumn
  row: RecordsTableRow
  schemas?: Schema[]
}) {
  // What every record has, not one of its values: its kind, its collection,
  // when it was last changed (a list of every kind shows these).
  if (col.type === 'kind') {
    const schema = schemas?.find((s) => s.name === row.schema_name)
    return (
      <Badge variant="accent">
        {displayLabel(row.schema_name ?? '', schema?.label)}
      </Badge>
    )
  }
  if (col.type === 'collection')
    return row.collection ? <>{row.collection}</> : <Dash />
  if (col.type === 'updated')
    return row.updated_at ? <>{formatDate(row.updated_at)}</> : <Dash />
  // The record's open threads of notes, not one of its values.
  if (col.type === 'notes') {
    const text = openNotesText(row.open_notes, row.latest_note)
    return text ? (
      <span className="block max-w-xs truncate" title={text}>
        {text}
      </span>
    ) : (
      <Dash />
    )
  }
  const value = row.data[col.name]
  if (value === undefined || value === null) return <Dash />
  if (col.type === 'reference' && typeof value === 'string')
    return (
      <ReferenceLink
        id={value}
        labels={row.reference_labels}
        collections={row.reference_collections}
      />
    )
  if (col.type === 'reference_list' && Array.isArray(value))
    return value.length === 0 ? (
      <Dash />
    ) : (
      <span className="flex flex-wrap gap-x-2 gap-y-1">
        {(value as string[]).map((id) => (
          <ReferenceLink
            key={id}
            id={id}
            labels={row.reference_labels}
            collections={row.reference_collections}
          />
        ))}
      </span>
    )
  if (
    col.type === 'file' ||
    col.type === 'file_list' ||
    // A projected column carries no type: a file reads as one by its shape.
    (col.type === undefined && fileRefsIn(value).length > 0)
  )
    return <FileCell value={value} />
  if (col.type === 'longtext' && typeof value === 'string')
    // One line in a table cell; the whole text is on hover.
    return (
      <span className="block max-w-xs truncate" title={value}>
        {value.replace(/\s*\n\s*/g, ' ')}
      </span>
    )
  return <>{formatCellValue(value)}</>
}

/** The records table shared by the collection detail page and the view
 * builder's live preview — same conventions (`—` for null/undefined,
 * badge-linked schema column, checkbox selection) in both places, with
 * per-caller pieces (ID column, Added column, sorting) opted into
 * individually since preview rows are column projections without a stable
 * record id. A row with a `recordLink` is clickable as a whole. */
export function RecordsTable({
  columns,
  rows,
  schemas,
  showSchemaColumn = false,
  showIdColumn = true,
  idHeader = 'ID',
  showAddedColumn = true,
  recordLink,
  selection,
  sort,
  onSortChange,
  trailing,
  totals,
}: RecordsTableProps) {
  const cols: DataTableColumn<RecordsTableRow>[] = []
  if (showIdColumn)
    cols.push({
      key: '__id',
      header: idHeader,
      width: '8rem',
      render: (r) =>
        r.natural_name ?? <span className="font-mono">{r.id.slice(0, 8)}</span>,
    })
  if (showSchemaColumn)
    cols.push({
      key: '__schema',
      header: 'Schema',
      width: '9rem',
      render: (r) => {
        const rowSchema = schemas?.find((s) => s.name === r.schema_name)
        const badge = (
          <Badge variant="accent">
            {displayLabel(r.schema_name ?? '', rowSchema?.label)}
          </Badge>
        )
        return rowSchema ? (
          <Link to={`/schemas/${rowSchema.id}`}>{badge}</Link>
        ) : (
          badge
        )
      },
    })
  for (const col of columns)
    cols.push({
      key: col.name,
      header: col.label,
      headerTitle: col.name,
      sortable: col.sortable !== false,
      render: (r) => <CellValue col={col} row={r} schemas={schemas} />,
    })
  if (showAddedColumn)
    cols.push({
      key: '__added',
      header: 'Added',
      width: '8rem',
      className: 'text-fg-muted',
      render: (r) => (r.created_at ? formatDate(r.created_at) : '—'),
    })
  if (trailing)
    cols.push({
      key: '__trailing',
      header: trailing.header,
      render: trailing.render,
    })

  return (
    <DataTable
      layout="auto"
      columns={cols}
      rows={rows}
      getRowId={(r) => r.id}
      rowHref={recordLink}
      selection={
        selection && {
          ...selection,
          allLabel: 'Select all records',
          rowLabel: (id) => {
            const r = rows.find((x) => x.id === id)
            return `Select record ${r?.natural_name ?? id.slice(0, 8)}`
          },
        }
      }
      sort={sort}
      onSortChange={onSortChange}
      emptyTitle="No records"
      footer={
        totals && (
          <tr className="bg-canvas-subtle text-xs text-fg-muted">
            {selection && <td />}
            {cols.map((c, i) => (
              <td key={c.key} className="px-4 py-2">
                {i === 0 ? totals.label : (totals.cells[c.key] ?? null)}
              </td>
            ))}
          </tr>
        )
      }
    />
  )
}
