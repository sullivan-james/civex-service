import { Badge, Table, Thead, Th, Tbody, Tr, Td } from '../ui'
import { formatBytes } from '../../utils/format'

// Renders one step input/output value, recognizing the shapes the backend's
// wire-protocol conversion (civex_plugin_sdk.io_convert) actually produces:
// a small `table`-typed value inlines full columnar/typed data, a large one
// (or bytes) gets summarized by executor._json_safe before it ever reaches
// the API -- see civex-plugin-sdk/src/civex_plugin_sdk/io_convert.py and
// src/civex/workflows/executor.py's _summarize_scratch_path_envelope.
// Anything else falls back to pretty-printed JSON.

const MAX_DISPLAYED_ROWS = 50

type Obj = Record<string, unknown>

function asObj(value: unknown): Obj | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Obj)
    : null
}

interface TableEnvelope {
  encoding: 'inline'
  columns: string[]
  dtypes: Record<string, string>
  data: Record<string, unknown[]>
}

function asTableEnvelope(value: unknown): TableEnvelope | null {
  const o = asObj(value)
  if (
    o &&
    o.encoding === 'inline' &&
    Array.isArray(o.columns) &&
    asObj(o.data)
  ) {
    return o as unknown as TableEnvelope
  }
  return null
}

function isBytesEnvelope(value: unknown): boolean {
  const o = asObj(value)
  return !!o && (o.encoding === 'base64' || o.encoding === 'path')
}

function asTableSummary(
  value: unknown,
): { table_rows: number | null; table_columns: string[] } | null {
  const o = asObj(value)
  return o && 'table_rows' in o && Array.isArray(o.table_columns)
    ? (o as unknown as { table_rows: number | null; table_columns: string[] })
    : null
}

function asDataFrameSummary(
  value: unknown,
): { rows: number; columns: string[] } | null {
  const o = asObj(value)
  return o &&
    !('encoding' in o) &&
    typeof o.rows === 'number' &&
    Array.isArray(o.columns)
    ? (o as unknown as { rows: number; columns: string[] })
    : null
}

function asBytesSummary(value: unknown): number | null | undefined {
  const o = asObj(value)
  if (!o || Object.keys(o).length !== 1 || !('bytes' in o)) return undefined
  return o.bytes as number | null
}

function TableSummaryBadge({
  rows,
  columns,
}: {
  rows: number | null
  columns: string[]
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <Badge variant="accent">table</Badge>
      <span className="text-fg-muted">
        {rows != null ? `${rows} row${rows === 1 ? '' : 's'}` : 'size unknown'}
        {columns.length > 0 && ` · ${columns.join(', ')}`}
      </span>
    </div>
  )
}

function cellText(v: unknown): string {
  return v === null || v === undefined ? '—' : String(v)
}

function InlineTable({ table }: { table: TableEnvelope }) {
  const rowCount = table.columns.length
    ? (table.data[table.columns[0]]?.length ?? 0)
    : 0
  const shown = Math.min(rowCount, MAX_DISPLAYED_ROWS)

  return (
    <div className="space-y-1">
      <TableSummaryBadge rows={rowCount} columns={[]} />
      <div className="max-h-64 overflow-auto">
        <Table>
          <Thead>
            <tr>
              {table.columns.map((c) => (
                <Th key={c}>
                  {c}
                  <span className="ml-1.5 normal-case font-normal text-fg-subtle">
                    {table.dtypes[c]}
                  </span>
                </Th>
              ))}
            </tr>
          </Thead>
          <Tbody>
            {Array.from({ length: shown }, (_, i) => (
              <Tr key={i}>
                {table.columns.map((c) => (
                  <Td key={c} className="font-mono text-xs whitespace-nowrap">
                    {cellText(table.data[c]?.[i])}
                  </Td>
                ))}
              </Tr>
            ))}
          </Tbody>
        </Table>
      </div>
      {rowCount > shown && (
        <p className="text-fg-muted">
          showing {shown} of {rowCount} rows
        </p>
      )}
    </div>
  )
}

export default function StepValueDisplay({ value }: { value: unknown }) {
  const table = asTableEnvelope(value)
  if (table) return <InlineTable table={table} />

  if (isBytesEnvelope(value)) {
    return <Badge variant="default">binary</Badge>
  }

  const tableSummary = asTableSummary(value)
  if (tableSummary) {
    return (
      <TableSummaryBadge
        rows={tableSummary.table_rows}
        columns={tableSummary.table_columns}
      />
    )
  }

  const dfSummary = asDataFrameSummary(value)
  if (dfSummary) {
    return (
      <TableSummaryBadge rows={dfSummary.rows} columns={dfSummary.columns} />
    )
  }

  const bytesSummary = asBytesSummary(value)
  if (bytesSummary !== undefined) {
    return (
      <Badge variant="default">
        {bytesSummary != null ? formatBytes(bytesSummary) : 'binary'}
      </Badge>
    )
  }

  if (value === null || value === undefined) {
    return <span className="font-mono text-fg-subtle">null</span>
  }
  if (
    typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean'
  ) {
    return <span className="font-mono text-fg">{String(value)}</span>
  }
  return (
    <pre className="font-mono text-fg whitespace-pre-wrap break-words">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}
