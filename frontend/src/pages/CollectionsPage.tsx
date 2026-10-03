import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useCollections, useCreateCollection } from '../hooks/useCollections'
import {
  Badge,
  Button,
  CreateResourceModal,
  Field,
  TimeZoneSelect,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  MonoId,
  Page,
  DataTable,
} from '../components/ui'
import { pluralise } from '../lib/utils'
import { errorMessage } from '../lib/errors'
import { dumpApi, type RestoreResult } from '../api/dump'
import { CollectionScopeFields } from '../components/collections/CollectionScopeFields'
import type { CollectionScope } from '../api/collections'

function CreateCollectionModal({ onClose }: { onClose: () => void }) {
  const create = useCreateCollection()
  const [timezone, setTimezone] = useState('')
  const [scope, setScope] = useState<CollectionScope>('local')
  const [schemas, setSchemas] = useState<string[]>([])

  return (
    <CreateResourceModal
      resourceLabel="collection"
      namePlaceholder="my-collection"
      onClose={onClose}
      isPending={create.isPending}
      error={create.error}
      extraFields={
        <>
          <Field
            label="Timezone"
            info="Datetimes without a UTC offset are read in this zone, and everyone sees them in it. Unset: each viewer's own timezone."
          >
            <TimeZoneSelect
              value={timezone}
              onChange={setTimezone}
              unsetLabel="Viewer's own"
              className="w-full"
            />
          </Field>
          <CollectionScopeFields
            scope={scope}
            onScopeChange={setScope}
            schemas={schemas}
            onSchemasChange={setSchemas}
          />
        </>
      }
      onSubmit={async ({ name, description }) => {
        await create.mutateAsync({
          name,
          description: description || undefined,
          timezone: timezone || undefined,
          scope,
          schemas,
        })
      }}
    />
  )
}

function ImportResultModal({
  result,
  onClose,
}: {
  result: RestoreResult
  onClose: () => void
}) {
  return (
    <Modal onClose={onClose} size="sm">
      <ModalHeader>Import complete</ModalHeader>
      <ModalBody>
        <dl className="text-sm space-y-1">
          <div className="flex justify-between">
            <dt className="text-fg-muted">Schemas</dt>
            <dd className="font-medium">{result.schemas}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-fg-muted">Collections</dt>
            <dd className="font-medium">{result.datasets}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-fg-muted">Records</dt>
            <dd className="font-medium">
              {result.records_restored}/{result.records_total}
              {result.records_restored < result.records_total && (
                <span className="ml-1 text-attention">
                  ({result.records_total - result.records_restored} skipped)
                </span>
              )}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-fg-muted">Workflows</dt>
            <dd className="font-medium">{result.workflows}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-fg-muted">Plugins</dt>
            <dd className="font-medium">{result.plugins}</dd>
          </div>
        </dl>
      </ModalBody>
      <ModalFooter>
        <Button variant="primary" onClick={onClose}>
          Done
        </Button>
      </ModalFooter>
    </Modal>
  )
}

export default function CollectionsPage() {
  const { data, isLoading, error } = useCollections()
  const queryClient = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const [importResult, setImportResult] = useState<RestoreResult | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  async function handleImportFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    setImporting(true)
    setImportError(null)
    try {
      const result = await dumpApi.importDump(file)
      setImportResult(result)
      queryClient.invalidateQueries()
    } catch (err) {
      setImportError(err instanceof Error ? err.message : String(err))
    } finally {
      setImporting(false)
    }
  }

  return (
    <Page
      title="Collections"
      action={
        <Button variant="primary" onClick={() => setShowCreate(true)}>
          New collection
        </Button>
      }
      secondaryActions={[
        { label: 'Export dump', onClick: () => dumpApi.exportDump() },
        {
          label: importing ? 'Importing…' : 'Import dump',
          onClick: () => fileInputRef.current?.click(),
          disabled: importing,
        },
      ]}
    >
      {showCreate && (
        <CreateCollectionModal onClose={() => setShowCreate(false)} />
      )}
      {importResult && (
        <ImportResultModal
          result={importResult}
          onClose={() => setImportResult(null)}
        />
      )}

      {/* Hidden file input for import */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".yaml,.yml"
        className="hidden"
        onChange={handleImportFile}
      />

      {importError && (
        <p role="alert" className="text-sm text-danger">
          {importError}
        </p>
      )}

      <DataTable
        layout="auto"
        columns={[
          {
            key: 'name',
            header: 'Name',
            render: (d) => <span className="font-medium">{d.name}</span>,
          },
          {
            key: 'records',
            header: 'Records',
            render: (d) => (
              <Badge variant={d.record_count > 0 ? 'success' : 'default'}>
                {pluralise(d.record_count, 'record')}
              </Badge>
            ),
          },
          {
            key: 'description',
            header: 'Description',
            className: 'text-fg-muted',
            render: (d) => d.description ?? '',
          },
          {
            key: 'id',
            header: 'ID',
            width: '7rem',
            render: (d) => <MonoId id={d.id} />,
          },
        ]}
        rows={data ?? []}
        getRowId={(d) => d.id}
        rowHref={(d) => `/collections/${d.id}`}
        isLoading={isLoading}
        error={error ? errorMessage(error) : undefined}
        emptyTitle="No collections yet"
        emptyAction={
          <Button variant="primary" onClick={() => setShowCreate(true)}>
            New collection
          </Button>
        }
      />
    </Page>
  )
}
