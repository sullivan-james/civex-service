import { useRef, useState } from 'react'
import { Link } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { useDatasets, useCreateDataset } from '../hooks/useDatasets'
import {
  Badge,
  Button,
  EmptyState,
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

function CreateDatasetModal({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const create = useCreateDataset()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    await create.mutateAsync({ name, description: description || undefined })
    onClose()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg border border-[#d0d7de] shadow-lg w-full max-w-md p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-base font-semibold text-[#1f2328] mb-4">
          New dataset
        </h2>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div>
            <label className="block text-xs font-medium text-[#1f2328] mb-1">
              Name <span className="text-[#d1242f]">*</span>
            </label>
            <input
              autoFocus
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-1.5 text-sm border border-[#d0d7de] rounded-md focus:outline-none focus:ring-2 focus:ring-[#0969da] focus:border-[#0969da]"
              placeholder="my-dataset"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#1f2328] mb-1">
              Description
            </label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full px-3 py-1.5 text-sm border border-[#d0d7de] rounded-md focus:outline-none focus:ring-2 focus:ring-[#0969da] focus:border-[#0969da]"
              placeholder="Optional"
            />
          </div>
          {create.error && (
            <p className="text-xs text-[#d1242f]">
              {errorMessage(create.error)}
            </p>
          )}
          <div className="flex justify-end gap-2 mt-1">
            <Button type="button" variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={create.isPending}>
              {create.isPending ? 'Creating…' : 'Create dataset'}
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg border border-[#d0d7de] shadow-lg w-full max-w-sm p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-base font-semibold text-[#1f2328] mb-3">
          Import complete
        </h2>
        <dl className="text-sm space-y-1">
          <div className="flex justify-between">
            <dt className="text-[#656d76]">Schemas</dt>
            <dd className="font-medium">{result.schemas}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-[#656d76]">Datasets</dt>
            <dd className="font-medium">{result.datasets}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-[#656d76]">Records</dt>
            <dd className="font-medium">
              {result.records_restored}/{result.records_total}
              {result.records_restored < result.records_total && (
                <span className="ml-1 text-[#9a6700]">
                  ({result.records_total - result.records_restored} skipped)
                </span>
              )}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-[#656d76]">Workflows</dt>
            <dd className="font-medium">{result.workflows}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-[#656d76]">Plugins</dt>
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

export default function DatasetsPage() {
  const { data, isLoading, error } = useDatasets()
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
        <CreateDatasetModal onClose={() => setShowCreate(false)} />
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
        title="Datasets"
        action={
          <div className="flex items-center gap-2">
            {importError && (
              <span className="text-xs text-[#d1242f]">{importError}</span>
            )}
            <Button
              variant="default"
              onClick={() => dumpApi.exportDump()}
              title="Download a YAML dump of all schemas, datasets, and records"
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
              New dataset
            </Button>
          </div>
        }
      />

      {isLoading && <LoadingState />}
      {error && <ErrorState message={errorMessage(error)} />}

      {data?.length === 0 && (
        <EmptyState
          title="No datasets yet"
          message="Create one with the button above."
        />
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
                    to={`/datasets/${d.id}`}
                    className="font-medium text-[#0969da] hover:underline"
                  >
                    {d.name}
                  </Link>
                </Td>
                <Td>
                  <Badge variant={d.record_count > 0 ? 'success' : 'default'}>
                    {pluralise(d.record_count, 'record')}
                  </Badge>
                </Td>
                <Td className="text-[#656d76]">{d.description ?? ''}</Td>
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
