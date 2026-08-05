import { useRef, useState } from 'react'
import { Link } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { useCollections, useCreateCollection } from '../hooks/useCollections'
import {
  Badge,
  Button,
  ErrorState,
  LoadingState,
  MonoId,
  PageHeader,
  Table,
  Tbody,
  Td,
  Th,
  Thead,
  Tr,
} from '../components/ui'
import { pluralise } from '../lib/utils'
import { errorMessage } from '../lib/errors'
import { dumpApi, type RestoreResult } from '../api/dump'

function CreateCollectionModal({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const create = useCreateCollection()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    await create.mutateAsync({ name, description: description || undefined })
    onClose()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-overlay-scrim"
      onClick={onClose}
    >
      <div
        className="bg-canvas rounded-lg border border-border shadow-lg w-full max-w-md p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-base font-semibold text-fg mb-4">New collection</h2>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div>
            <label className="block text-xs font-medium text-fg mb-1">
              Name <span className="text-danger">*</span>
            </label>
            <input
              autoFocus
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-1.5 text-sm border border-border rounded-md focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent"
              placeholder="my-collection"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-fg mb-1">
              Description
            </label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full px-3 py-1.5 text-sm border border-border rounded-md focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent"
              placeholder="Optional"
            />
          </div>
          {create.error && (
            <p className="text-xs text-danger">{errorMessage(create.error)}</p>
          )}
          <div className="flex justify-end gap-2 mt-1">
            <Button type="button" variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={create.isPending}>
              {create.isPending ? 'Creating…' : 'Create collection'}
            </Button>
          </div>
        </form>
      </div>
    </div>
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
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-overlay-scrim"
      onClick={onClose}
    >
      <div
        className="bg-canvas rounded-lg border border-border shadow-lg w-full max-w-sm p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-base font-semibold text-fg mb-3">
          Import complete
        </h2>
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
        <div className="flex justify-end mt-4">
          <Button variant="primary" onClick={onClose}>
            Done
          </Button>
        </div>
      </div>
    </div>
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
    <>
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

      <PageHeader
        title="Collections"
        action={
          <div className="flex items-center gap-2">
            {importError && (
              <span className="text-xs text-danger">{importError}</span>
            )}
            <Button
              variant="default"
              onClick={() => dumpApi.exportDump()}
              title="Download a YAML dump of all schemas, collections, and records"
            >
              Export dump
            </Button>
            <Button
              variant="default"
              onClick={() => fileInputRef.current?.click()}
              disabled={importing}
              title="Restore from a civex-dump.yaml file"
            >
              {importing ? 'Importing…' : 'Import dump'}
            </Button>
            <Button variant="primary" onClick={() => setShowCreate(true)}>
              New collection
            </Button>
          </div>
        }
      />

      {isLoading && <LoadingState />}
      {error && <ErrorState message={errorMessage(error)} />}

      {data?.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <svg
            width="40"
            height="40"
            viewBox="0 0 16 16"
            fill="none"
            className="mb-4 text-border"
            aria-hidden
          >
            <rect
              x="1"
              y="3"
              width="14"
              height="10"
              rx="2"
              stroke="currentColor"
              strokeWidth="1.5"
            />
            <path
              d="M4 7h8M4 9.5h5"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
          <h2 className="text-lg font-semibold text-fg mb-2">
            No collections yet
          </h2>
          <p className="text-sm text-fg-muted mb-6 max-w-sm">
            A collection is a named container for your records. Create one to
            start adding data.
          </p>
          <Button variant="primary" onClick={() => setShowCreate(true)}>
            Create collection
          </Button>
        </div>
      )}

      {data && data.length > 0 && (
        <Table>
          <Thead>
            <tr>
              <Th>Name</Th>
              <Th>Records</Th>
              <Th>Description</Th>
              <Th className="w-28">ID</Th>
            </tr>
          </Thead>
          <Tbody>
            {data.map((d) => (
              <Tr key={d.id}>
                <Td>
                  <Link
                    to={`/collections/${d.id}`}
                    className="font-medium text-accent hover:underline"
                  >
                    {d.name}
                  </Link>
                </Td>
                <Td>
                  <Badge variant={d.record_count > 0 ? 'success' : 'default'}>
                    {pluralise(d.record_count, 'record')}
                  </Badge>
                </Td>
                <Td className="text-fg-muted">{d.description ?? ''}</Td>
                <Td>
                  <MonoId id={d.id} />
                </Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}
    </>
  )
}
