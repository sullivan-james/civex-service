import { useState } from 'react'
import {
  useDeletedSchemas,
  useRestoreSchema,
  usePurgeSchema,
} from '../hooks/useSchemas'
import {
  useDeletedCollections,
  useRestoreCollection,
  usePurgeCollection,
} from '../hooks/useCollections'
import {
  useDeletedRecords,
  useRestoreRecord,
  usePurgeRecord,
} from '../hooks/useRecords'
import { useRetentionSettings } from '../hooks/useUISettings'
import {
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  MonoId,
  Page,
  Table,
  Tbody,
  Td,
  Th,
  Thead,
  Tr,
  TableSkeleton,
} from '../components/ui'
import { formatDate } from '../lib/utils'
import { errorMessage } from '../lib/errors'
import { displayLabel } from '../utils/naming'

type Kind = 'schema' | 'collection' | 'record'

const KIND_LABELS: Record<Kind, string> = {
  schema: 'Schemas',
  collection: 'Collections',
  record: 'Records',
}

interface Row {
  key: string
  label: string
  detail?: string
  deletedAt: string
  onRestore: () => void
  onPurge: () => void
  isRestoring: boolean
  isPurging: boolean
}

function RowActions({
  row,
  onConfirmPurge,
}: {
  row: Row
  onConfirmPurge: () => void
}) {
  return (
    <div className="flex items-center justify-end gap-2">
      <Button
        variant="default"
        size="sm"
        onClick={row.onRestore}
        disabled={row.isRestoring || row.isPurging}
      >
        {row.isRestoring ? 'Restoring…' : 'Restore'}
      </Button>
      <Button
        variant="danger"
        size="sm"
        onClick={onConfirmPurge}
        disabled={row.isRestoring || row.isPurging}
      >
        Delete permanently
      </Button>
    </div>
  )
}

export default function RecentlyDeletedPage() {
  const [kind, setKind] = useState<Kind>('schema')
  const [purgeTarget, setPurgeTarget] = useState<Row | null>(null)

  const { data: retention } = useRetentionSettings()

  const schemas = useDeletedSchemas()
  const collections = useDeletedCollections()
  const records = useDeletedRecords()

  const restoreSchema = useRestoreSchema()
  const purgeSchema = usePurgeSchema()
  const restoreCollection = useRestoreCollection()
  const purgeCollection = usePurgeCollection()
  const restoreRecord = useRestoreRecord()
  const purgeRecord = usePurgeRecord()

  const counts: Record<Kind, number> = {
    schema: schemas.data?.length ?? 0,
    collection: collections.data?.length ?? 0,
    record: records.data?.length ?? 0,
  }

  const active = { schemas, collections, records }[
    kind === 'schema'
      ? 'schemas'
      : kind === 'collection'
        ? 'collections'
        : 'records'
  ]

  const rows: Row[] =
    kind === 'schema'
      ? (schemas.data ?? []).map((s) => ({
          key: s.id,
          label: displayLabel(s.name, s.label),
          detail: s.name,
          deletedAt: s.deleted_at!,
          onRestore: () => restoreSchema.mutate(s.name),
          onPurge: () => purgeSchema.mutate(s.name),
          isRestoring:
            restoreSchema.isPending && restoreSchema.variables === s.name,
          isPurging: purgeSchema.isPending && purgeSchema.variables === s.name,
        }))
      : kind === 'collection'
        ? (collections.data ?? []).map((c) => ({
            key: c.id,
            label: c.name,
            detail: `${c.record_count} record${c.record_count === 1 ? '' : 's'}`,
            deletedAt: c.deleted_at!,
            onRestore: () => restoreCollection.mutate(c.name),
            onPurge: () => purgeCollection.mutate(c.name),
            isRestoring:
              restoreCollection.isPending &&
              restoreCollection.variables === c.name,
            isPurging:
              purgeCollection.isPending && purgeCollection.variables === c.name,
          }))
        : (records.data ?? []).map((r) => ({
            key: r.id,
            label: r.natural_name ?? r.id,
            detail: r.schema_name,
            deletedAt: r.deleted_at!,
            onRestore: () => restoreRecord.mutate(r.id),
            onPurge: () => purgeRecord.mutate(r.id),
            isRestoring:
              restoreRecord.isPending && restoreRecord.variables === r.id,
            isPurging: purgeRecord.isPending && purgeRecord.variables === r.id,
          }))

  return (
    <Page
      title="Recently Deleted"
      description={
        retention
          ? `Restorable for ${retention.purge_after_days} day${
              retention.purge_after_days === 1 ? '' : 's'
            } after deletion, then eligible for permanent deletion. Configurable in Settings.`
          : undefined
      }
    >
      <div className="flex items-center gap-2">
        {(Object.keys(KIND_LABELS) as Kind[]).map((k) => (
          <button
            key={k}
            onClick={() => setKind(k)}
            className={`px-3 py-2 text-xs rounded-full border transition-colors ${
              kind === k
                ? 'bg-accent text-fg-on-emphasis border-accent'
                : 'bg-canvas text-fg-muted border-border hover:bg-canvas-subtle'
            }`}
          >
            {KIND_LABELS[k]} ({counts[k]})
          </button>
        ))}
      </div>

      {active.isLoading && (
        <TableSkeleton columns={['w-48', 'w-32', 'w-24', 'w-40']} rows={6} />
      )}
      {active.error && <ErrorState message={errorMessage(active.error)} />}

      {!active.isLoading && !active.error && rows.length === 0 && (
        <EmptyState
          title={`No deleted ${KIND_LABELS[kind].toLowerCase()}`}
          message={`Items you delete show up here${
            retention ? ` for ${retention.purge_after_days} days` : ''
          }, with a Restore action.`}
        />
      )}

      {rows.length > 0 && (
        <Table>
          <Thead>
            <tr>
              <Th>Name</Th>
              <Th>
                {kind === 'record'
                  ? 'Schema'
                  : kind === 'collection'
                    ? 'Records'
                    : 'Name'}
              </Th>
              <Th>Deleted</Th>
              <Th className="text-right">Actions</Th>
            </tr>
          </Thead>
          <Tbody>
            {rows.map((row) => (
              <Tr key={row.key}>
                <Td className="font-medium text-fg">
                  {kind === 'record' ? <MonoId id={row.key} /> : row.label}
                </Td>
                <Td className="text-fg-muted">
                  {kind === 'record' ? row.detail : (row.detail ?? row.label)}
                </Td>
                <Td className="text-fg-muted">{formatDate(row.deletedAt)}</Td>
                <Td>
                  <RowActions
                    row={row}
                    onConfirmPurge={() => setPurgeTarget(row)}
                  />
                </Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}

      {purgeTarget && (
        <ConfirmDialog
          title="Delete permanently"
          body={`Permanently delete '${purgeTarget.label}'? This cannot be undone.`}
          confirmLabel="Delete permanently"
          variant="danger"
          isPending={purgeTarget.isPurging}
          onConfirm={() => {
            purgeTarget.onPurge()
            setPurgeTarget(null)
          }}
          onClose={() => setPurgeTarget(null)}
        />
      )}
    </Page>
  )
}
