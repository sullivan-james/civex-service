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
  DataTable,
  MonoId,
  Page,
  TabNav,
  TabPanel,
  useTabParam,
} from '../components/ui'
import { formatDate } from '../lib/utils'
import { errorMessage } from '../lib/errors'
import { displayLabel } from '../utils/naming'

type Kind = 'schema' | 'collection' | 'record'
const KIND_TABS = [
  { id: 'schema' },
  { id: 'collection' },
  { id: 'record' },
] as const

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
  const busy = row.isRestoring || row.isPurging
  return (
    <>
      <Button size="sm" onClick={row.onRestore} disabled={busy}>
        {row.isRestoring ? 'Restoring…' : 'Restore'}
      </Button>
      <Button
        size="sm"
        variant="danger"
        onClick={onConfirmPurge}
        disabled={busy}
      >
        Delete
      </Button>
    </>
  )
}

export default function RecentlyDeletedPage() {
  const [kind, setKind] = useTabParam<Kind>(KIND_TABS, 'schema', 'kind')
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
      info={
        retention
          ? `Restorable for ${retention.purge_after_days} day${
              retention.purge_after_days === 1 ? '' : 's'
            } after deletion, then eligible for permanent deletion.`
          : undefined
      }
      tabs={
        <TabNav
          label="Kind of deleted item"
          value={kind}
          onChange={setKind}
          tabs={(Object.keys(KIND_LABELS) as Kind[]).map((k) => ({
            id: k,
            label: `${KIND_LABELS[k]} (${counts[k]})`,
          }))}
        />
      }
    >
      <TabPanel id={kind} value={kind}>
        <DataTable
          layout="auto"
          columns={[
            {
              key: 'name',
              header: 'Name',
              className: 'font-medium',
              render: (row) =>
                kind === 'record' ? <MonoId id={row.key} /> : row.label,
            },
            {
              key: 'detail',
              header:
                kind === 'record'
                  ? 'Schema'
                  : kind === 'collection'
                    ? 'Records'
                    : 'Name',
              className: 'text-fg-muted',
              render: (row) =>
                kind === 'record' ? row.detail : (row.detail ?? row.label),
            },
            {
              key: 'deleted',
              header: 'Deleted',
              className: 'text-fg-muted',
              render: (row) => formatDate(row.deletedAt),
            },
          ]}
          rows={rows}
          getRowId={(row) => row.key}
          isLoading={active.isLoading}
          error={active.error ? errorMessage(active.error) : undefined}
          emptyTitle={`No deleted ${KIND_LABELS[kind].toLowerCase()}`}
          actionsWidth="14rem"
          actions={(row) => (
            <RowActions row={row} onConfirmPurge={() => setPurgeTarget(row)} />
          )}
        />
      </TabPanel>

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
