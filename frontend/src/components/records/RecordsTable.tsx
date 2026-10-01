import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { Table, Thead, Th, Tbody, Tr, Td, Checkbox, Badge } from '../ui'
import { ChevronUp, ChevronDown } from '../ui/icons'
import { displayLabel } from '../../utils/naming'
import { formatDate } from '../../lib/utils'
import { ReferenceLink } from './ReferenceLink'
import type { Schema } from '../../api/schemas'

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
  reference_labels?: Record<string, string | null> | null
  reference_collections?: Record<string, string> | null
  child_counts?: Record<string, number> | null
}

export interface RecordsTableSort {
  key: string
  direction: 'asc' | 'desc'
}

export interface RecordsTableSelection {
  selected: Set<string>
  onToggle: (id: string) => void
  onToggleAll: () => void
}

export interface RecordsTableProps {
  columns: RecordsTableColumn[]
  rows: RecordsTableRow[]
  /** Resolves schema badges — only used when `showSchemaColumn` is true. */
  schemas?: Schema[]
  showSchemaColumn?: boolean
  showIdColumn?: boolean
  showAddedColumn?: boolean
  /** Renders the ID cell as a link when provided; plain text otherwise. */
  recordLink?: (row: RecordsTableRow) => string
  selection?: RecordsTableSelection
  sort?: RecordsTableSort
  onSortChange?: (columnName: string) => void
  /** An extra last column -- e.g. links down to a row's children. */
  trailing?: { header: string; render: (row: RecordsTableRow) => ReactNode }
}

function formatCellValue(value: unknown): string {
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/** The records table shared by the collection detail page and the view
 * builder's live preview — same header/cell markup and conventions
 * (`—` for null/undefined, badge-linked schema column, checkbox
 * selection) in both places, with per-caller pieces (ID column, Added
 * column, sorting) opted into individually since preview rows are
 * column projections without a stable record id. */
export function RecordsTable({
  columns,
  rows,
  schemas,
  showSchemaColumn = false,
  showIdColumn = true,
  showAddedColumn = true,
  recordLink,
  selection,
  sort,
  onSortChange,
  trailing,
}: RecordsTableProps) {
  return (
    <Table>
      <Thead>
        <tr>
          {selection && (
            <Th className="w-8">
              <Checkbox
                aria-label="Select all records"
                checked={
                  selection.selected.size === rows.length && rows.length > 0
                }
                ref={(el) => {
                  if (el)
                    el.indeterminate =
                      selection.selected.size > 0 &&
                      selection.selected.size < rows.length
                }}
                onChange={selection.onToggleAll}
              />
            </Th>
          )}
          {showIdColumn && <Th className="w-24">ID</Th>}
          {showSchemaColumn && <Th className="w-32">Schema</Th>}
          {columns.map((col) => {
            const activeDirection =
              sort && sort.key === col.name ? sort.direction : undefined
            return (
              <Th
                key={col.name}
                title={col.name}
                sortDirection={
                  onSortChange && col.sortable !== false
                    ? (activeDirection ?? 'none')
                    : undefined
                }
              >
                {onSortChange && col.sortable !== false ? (
                  <button
                    type="button"
                    onClick={() => onSortChange(col.name)}
                    className="group inline-flex items-center gap-1 cursor-pointer hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent rounded-sm"
                  >
                    {col.label}
                    {activeDirection === 'asc' ? (
                      <ChevronUp size={12} className="shrink-0" />
                    ) : activeDirection === 'desc' ? (
                      <ChevronDown size={12} className="shrink-0" />
                    ) : (
                      <ChevronDown
                        size={12}
                        className="shrink-0 opacity-0 group-hover:opacity-100"
                      />
                    )}
                  </button>
                ) : (
                  col.label
                )}
              </Th>
            )
          })}
          {showAddedColumn && <Th className="w-32">Added</Th>}
          {trailing && <Th>{trailing.header}</Th>}
        </tr>
      </Thead>
      <Tbody>
        {rows.map((r) => (
          <Tr key={r.id}>
            {selection && (
              <Td>
                <Checkbox
                  aria-label={`Select record ${r.natural_name ?? r.id.slice(0, 8)}`}
                  checked={selection.selected.has(r.id)}
                  onChange={() => selection.onToggle(r.id)}
                />
              </Td>
            )}
            {showIdColumn &&
              (recordLink ? (
                <Td>
                  <Link
                    to={recordLink(r)}
                    className="text-sm text-accent hover:underline"
                  >
                    {r.natural_name ?? (
                      <span className="font-mono">{r.id.slice(0, 8)}</span>
                    )}
                  </Link>
                </Td>
              ) : (
                <Td>
                  {r.natural_name ?? (
                    <span className="font-mono">{r.id.slice(0, 8)}</span>
                  )}
                </Td>
              ))}
            {showSchemaColumn && (
              <Td>
                {(() => {
                  const rowSchema = schemas?.find(
                    (s) => s.name === r.schema_name,
                  )
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
                })()}
              </Td>
            )}
            {columns.map((col) => {
              const value = r.data[col.name]
              return (
                <Td key={col.name} className="text-fg">
                  {value === undefined || value === null ? (
                    <span className="text-fg-subtle">—</span>
                  ) : col.type === 'reference' && typeof value === 'string' ? (
                    <ReferenceLink
                      id={value}
                      labels={r.reference_labels}
                      collections={r.reference_collections}
                    />
                  ) : col.type === 'reference_list' && Array.isArray(value) ? (
                    value.length === 0 ? (
                      <span className="text-fg-subtle">—</span>
                    ) : (
                      <span className="flex flex-wrap gap-x-2 gap-y-1">
                        {(value as string[]).map((id) => (
                          <ReferenceLink
                            key={id}
                            id={id}
                            labels={r.reference_labels}
                            collections={r.reference_collections}
                          />
                        ))}
                      </span>
                    )
                  ) : (
                    formatCellValue(value)
                  )}
                </Td>
              )
            })}
            {showAddedColumn && (
              <Td className="text-fg-muted">
                {r.created_at ? formatDate(r.created_at) : '—'}
              </Td>
            )}
            {trailing && <Td>{trailing.render(r)}</Td>}
          </Tr>
        ))}
      </Tbody>
    </Table>
  )
}
