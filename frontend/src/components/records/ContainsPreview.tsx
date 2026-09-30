import { useMemo } from 'react'
import { Link, useNavigate } from 'react-router'
import type { Schema } from '../../api/schemas'
import { useRecordCounts, useRecordPage } from '../../hooks/useRecords'
import { useSchemas } from '../../hooks/useSchemas'
import { Plus } from '../ui/icons'
import { Button, TableSkeleton } from '../ui'
import { DrillLinks } from '../explorer/DrillLinks'
import { columnLabel } from '../views/ColumnPicker'
import { applyExplorerPatch } from '../../utils/explorerState'
import {
  defaultColumnNames,
  schemaLevels,
  schemasById,
} from '../../utils/hierarchy'
import { collectFields, joinableColumns } from '../../utils/viewFields'
import { displayLabel } from '../../utils/naming'
import { RecordsTable } from './RecordsTable'
import { toTableRows } from './tableRows'

/** Rows shown per schema; the rest are one click away in the full list. */
const PEEK = 3
/** Columns shown per row, after the name. */
const PEEK_COLUMNS = 3

/** What sits under a record, at a glance: for each schema below it, a short
 * peek at its first few records in the same table the collection page uses,
 * with links to the full list (the explorer, scoped to this record), to add
 * one, and down into each row's own children. Nothing here browses: paging,
 * search, filters and bulk actions stay in the explorer. */
export function ContainsPreview({
  record,
  collection,
  collectionId,
  pollMs,
}: {
  record: { id: string; schema_name: string }
  collection: string
  collectionId: string
  pollMs?: number | false
}) {
  const { data: schemaList } = useSchemas()
  const schemas = useMemo(() => schemaList ?? [], [schemaList])
  const { data: counts } = useRecordCounts(collection, { within: record.id })
  const own = schemas.find((s) => s.name === record.schema_name)

  // Every schema below the record that has records here, plus its direct
  // children even when empty, so there is always somewhere to add one.
  const blocks = useMemo(
    () =>
      own
        ? schemaLevels(schemas, own).filter(
            ({ schema, depth }) =>
              depth === 0 || (counts?.[schema.name] ?? 0) > 0,
          )
        : [],
    [schemas, own, counts],
  )

  if (!own || blocks.length === 0) return null
  return (
    <div className="space-y-4">
      {blocks.map(({ schema, depth }) => (
        <SchemaPeek
          key={schema.id}
          schema={schema}
          schemas={schemas}
          count={counts?.[schema.name] ?? 0}
          direct={depth === 0}
          recordId={record.id}
          collection={collection}
          collectionId={collectionId}
          pollMs={pollMs}
        />
      ))}
    </div>
  )
}

function SchemaPeek({
  schema,
  schemas,
  count,
  direct,
  recordId,
  collection,
  collectionId,
  pollMs,
}: {
  schema: Schema
  schemas: Schema[]
  count: number
  /** A child of the record's own schema -- the only kind it can be the
   * parent of, so the only kind offered an Add. */
  direct: boolean
  recordId: string
  collection: string
  collectionId: string
  pollMs?: number | false
}) {
  const navigate = useNavigate()
  const byId = useMemo(() => schemasById(schemas), [schemas])
  const byName = useMemo(
    () => new Map(schemas.map((s) => [s.name, s])),
    [schemas],
  )
  const baseFields = useMemo(() => collectFields(schema, byId), [schema, byId])
  const joinable = useMemo(
    () => joinableColumns(schema, byId, byName),
    [schema, byId, byName],
  )
  const names = defaultColumnNames(schema).slice(0, PEEK_COLUMNS)
  const page = useRecordPage(
    { datasetName: collection, schemaName: schema.name },
    {
      schema: schema.name,
      within: recordId,
      columns: names,
      child_counts: true,
      limit: PEEK,
    },
    { refetchInterval: pollMs },
  )

  const label = displayLabel(schema.name, schema.label)
  const listHref = (patch: { schema: string; within: string }) =>
    `/collections/${collectionId}?${applyExplorerPatch(new URLSearchParams(), patch)}`
  const rows = toTableRows(page.data?.items ?? [])
  const total = page.data?.total ?? count

  return (
    <div className="overflow-hidden rounded-md border border-border">
      <div className="flex items-center justify-between gap-3 bg-canvas-subtle px-3 py-2">
        <h3 className="text-sm font-semibold text-fg">
          {label}
          <span className="ml-2 font-normal text-fg-muted">
            {total.toLocaleString()}
          </span>
        </h3>
        <div className="flex gap-2">
          {total > 0 && (
            <Link to={listHref({ schema: schema.name, within: recordId })}>
              <Button size="sm">View all</Button>
            </Link>
          )}
          {direct && (
            <Link
              to={`/collections/${collectionId}/new?${new URLSearchParams({
                schema: schema.name,
                parent: recordId,
              })}`}
            >
              <Button size="sm" variant="primary">
                <Plus size={14} /> Add
              </Button>
            </Link>
          )}
        </div>
      </div>
      {page.isLoading ? (
        <TableSkeleton columns={['w-24', 'w-24', 'w-24']} rows={PEEK} />
      ) : rows.length === 0 ? (
        <p className="px-3 py-4 text-sm text-fg-muted">
          No {label.toLowerCase()} yet.
        </p>
      ) : (
        <RecordsTable
          columns={names.map((name) => ({
            name,
            label: columnLabel(name, baseFields, joinable),
            type: baseFields.find((f) => f.name === name)?.type,
            sortable: false,
          }))}
          rows={rows}
          schemas={schemas}
          showAddedColumn={false}
          recordLink={(r) => `/records/${r.id}`}
          trailing={{
            header: 'Contains',
            render: (row) => (
              <DrillLinks
                counts={row.child_counts}
                byName={byName}
                onDrill={(child) =>
                  navigate(listHref({ schema: child, within: row.id }))
                }
              />
            ),
          }}
        />
      )}
      {total > rows.length && rows.length > 0 && (
        <Link
          to={listHref({ schema: schema.name, within: recordId })}
          className="block border-t border-border-muted px-3 py-2 text-sm font-medium text-accent hover:underline"
        >
          Show {(total - rows.length).toLocaleString()} more in the full list
        </Link>
      )}
    </div>
  )
}
