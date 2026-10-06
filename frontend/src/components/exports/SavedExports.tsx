import { useState } from 'react'
import type { ExportDefinition } from '../../api/exportDefinitions'
import type { Schema } from '../../api/schemas'
import { useCollections } from '../../hooks/useCollections'
import {
  useAllExports,
  useDeleteExportDefinition,
} from '../../hooks/useExportDefinitions'
import { useListParams } from '../../hooks/useListParams'
import { errorMessage } from '../../lib/errors'
import { describeDefinition } from '../../utils/exportBuilder'
import { schemaLevels } from '../../utils/hierarchy'
import { displayLabel } from '../../utils/naming'
import {
  Button,
  ConfirmDialog,
  DataTable,
  ListToolbar,
  Pagination,
  type DataTableColumn,
} from '../ui'
import { Plus } from '../ui/icons'
import { ExportButton } from '../files/ExportButton'
import { definitionPreset } from './exportPresets'

const COLUMN_NAME = 'name'
const COLUMN_SCHEMA = 'schema'

/** The exports that have been saved, as a list like every other: search it,
 * narrow it to the kind of record it starts from, sort it, page through it. Make
 * one, change one, delete one, and (with a collection chosen) run one. The one
 * place exports are looked after.
 *
 * An export *starts from* a kind of record (an Encounter): it takes that kind
 * and everything inside it, and is offered on each of those pages and on the
 * collections that use them. It is run on a collection or within a record, which
 * is where it gets its data. */
export function SavedExports({ schemas }: { schemas: Schema[] }) {
  const { data, isLoading, error } = useAllExports()
  const { data: collections = [] } = useCollections()
  const list = useListParams('', ['schema', 'collection'])
  const remove = useDeleteExportDefinition()
  const [deleting, setDeleting] = useState<ExportDefinition | null>(null)

  const live = schemas.filter((s) => !s.deleted_at)
  const byName = (name: string) => schemas.find((s) => s.name === name)
  const label = (name: string) => displayLabel(name, byName(name)?.label)
  const runOn = collections.find((c) => c.name === list.picks.collection)?.name

  const wanted = list.q.trim().toLowerCase()
  const matching = (data ?? []).filter(
    (e) =>
      (!list.picks.schema || e.schema_name === list.picks.schema) &&
      (!wanted ||
        `${e.name} ${describeDefinition(e, schemas)}`
          .toLowerCase()
          .includes(wanted)),
  )
  const sortKey = list.sort?.field
  const sorted = [...matching].sort((a, b) => {
    const [x, y] =
      sortKey === COLUMN_SCHEMA
        ? [label(a.schema_name), label(b.schema_name)]
        : [a.name, b.name]
    return (list.sort?.dir === 'desc' ? -1 : 1) * x.localeCompare(y)
  })
  const shown = sorted.slice(list.page * list.size, (list.page + 1) * list.size)

  // Each export is a page of its own: a new one starts from the kind filtered to.
  const newHref = `/exports/new${
    byName(list.picks.schema)
      ? `?schema=${encodeURIComponent(list.picks.schema)}`
      : ''
  }`
  const editHref = (e: ExportDefinition) =>
    `/exports/${encodeURIComponent(e.schema_name)}/${encodeURIComponent(e.name)}`

  const columns: DataTableColumn<ExportDefinition>[] = [
    {
      key: COLUMN_NAME,
      header: 'Name',
      sortable: true,
      render: (e) => <span className="font-medium text-fg">{e.name}</span>,
    },
    {
      key: COLUMN_SCHEMA,
      header: 'Starts from',
      headerTitle:
        'The kind of record it starts from: it takes that kind and everything inside it, and is offered on each of those pages.',
      sortable: true,
      render: (e) => label(e.schema_name),
    },
    {
      key: 'takes',
      header: 'Takes',
      render: (e) => (
        <span className="text-fg-muted">{describeDefinition(e, schemas)}</span>
      ),
    },
  ]

  const filtered = !!list.q || !!list.picks.schema

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ListToolbar
          search={{
            value: list.q,
            label: 'Search exports',
            onChange: (q) => list.set({ q }),
          }}
          picks={[
            {
              label: 'Starts from…',
              value: list.picks.schema,
              options: [
                { value: '', label: 'Starts from…' },
                ...schemaLevels(live).map((l) => ({
                  value: l.schema.name,
                  label: displayLabel(l.schema.name, l.schema.label),
                })),
              ],
              onChange: (schema) => list.set({ schema }),
            },
            {
              label: 'Run on…',
              value: runOn ?? '',
              options: [
                { value: '', label: 'Run on…' },
                ...collections.map((c) => ({ value: c.name, label: c.name })),
              ],
              onChange: (collection) => list.set({ collection }),
            },
          ]}
        />
        <Button variant="primary" size="md" to={newHref}>
          <Plus size={14} aria-hidden="true" /> New export
        </Button>
      </div>

      <DataTable
        dense
        layout="auto"
        columns={columns}
        rows={shown}
        getRowId={(e) => e.id}
        isLoading={isLoading}
        error={error ? errorMessage(error) : undefined}
        rowHref={editHref}
        sort={
          list.sort
            ? { key: list.sort.field, direction: list.sort.dir }
            : undefined
        }
        onSortChange={list.toggleSort}
        emptyTitle={filtered ? 'No exports match' : 'No exports yet'}
        emptyMessage={
          filtered
            ? 'Try a different search or kind of record.'
            : 'Choose which files and tables to export, and how to lay out the folder.'
        }
        actions={(e) => (
          <span className="inline-flex gap-1">
            {runOn ? (
              <ExportButton
                size="sm"
                selection={{ collection: runOn }}
                folderName={`${runOn}-${e.name}`}
                preset={definitionPreset(e, runOn, schemas)}
                label="Run…"
              />
            ) : (
              <Button
                size="sm"
                disabled
                title="Choose a collection to run on, above"
              >
                Run…
              </Button>
            )}
            <Button size="sm" to={editHref(e)}>
              Edit
            </Button>
            <Button size="sm" variant="danger" onClick={() => setDeleting(e)}>
              Delete
            </Button>
          </span>
        )}
        actionsLabel="Actions"
        actionsWidth="230px"
      />
      <Pagination
        page={list.page}
        pageSize={list.size}
        total={matching.length}
        onPage={(page) => list.set({ page })}
        onPageSize={(size) => list.set({ size })}
      />

      {deleting && (
        <ConfirmDialog
          title={`Delete “${deleting.name}”?`}
          body={<p>Folders it has already made are not touched.</p>}
          confirmLabel="Delete export"
          variant="danger"
          isPending={remove.isPending}
          warning={remove.error ? errorMessage(remove.error) : undefined}
          onConfirm={() =>
            remove.mutate(
              { schema: deleting.schema_name, name: deleting.name },
              { onSuccess: () => setDeleting(null) },
            )
          }
          onClose={() => setDeleting(null)}
        />
      )}
    </div>
  )
}
