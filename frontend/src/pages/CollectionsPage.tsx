import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useCollections, useCreateCollection } from '../hooks/useCollections'
import {
  Badge,
  Button,
  CreateResourceModal,
  Field,
  TimeZoneSelect,
  MonoId,
  Page,
  DataTable,
  TabNav,
  TabPanel,
  useTabParam,
} from '../components/ui'
import { RecordsExplorer } from '../components/explorer/RecordsExplorer'
import { pluralise } from '../lib/utils'
import { errorMessage } from '../lib/errors'
import { bundleApi, type BundleImportResult } from '../api/bundle'
import {
  BundleImportResultModal,
  ExportBundleDialog,
} from '../components/collections/BundleDialogs'
import { CollectionScopeFields } from '../components/collections/CollectionScopeFields'
import type { CollectionScope } from '../api/collections'

const TABS = [{ id: 'list' }, { id: 'records' }] as const

function CreateCollectionModal({ onClose }: { onClose: () => void }) {
  const create = useCreateCollection()
  const [timezone, setTimezone] = useState('')
  const [scope, setScope] = useState<CollectionScope>('local')

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
          <CollectionScopeFields scope={scope} onScopeChange={setScope} />
        </>
      }
      onSubmit={async ({ name, description }) => {
        await create.mutateAsync({
          name,
          description: description || undefined,
          timezone: timezone || undefined,
          scope,
        })
      }}
    />
  )
}

export default function CollectionsPage() {
  const { data, isLoading, error } = useCollections()
  const queryClient = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const [importResult, setImportResult] = useState<BundleImportResult | null>(
    null,
  )
  const [showExport, setShowExport] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  // The collections, or every collection's records (and their files) in the
  // one explorer, so the whole project can be searched and triaged at once.
  const [tab, setTab] = useTabParam(TABS, 'list')

  async function handleImportFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    setImporting(true)
    setImportError(null)
    try {
      const result = await bundleApi.import(file)
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
      tabs={
        <TabNav
          label="Collections"
          value={tab}
          onChange={setTab}
          tabs={[
            { id: 'list' as const, label: 'Collections' },
            { id: 'records' as const, label: 'All records' },
          ]}
        />
      }
      action={
        <Button variant="primary" onClick={() => setShowCreate(true)}>
          New collection
        </Button>
      }
      secondaryActions={[
        { label: 'Export bundle…', onClick: () => setShowExport(true) },
        {
          label: importing ? 'Importing…' : 'Import bundle…',
          onClick: () => fileInputRef.current?.click(),
          disabled: importing,
        },
      ]}
    >
      {showCreate && (
        <CreateCollectionModal onClose={() => setShowCreate(false)} />
      )}
      {showExport && (
        <ExportBundleDialog onClose={() => setShowExport(false)} />
      )}
      {importResult && (
        <BundleImportResultModal
          result={importResult}
          onClose={() => setImportResult(null)}
        />
      )}

      {/* Hidden file input for import */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".zip"
        className="hidden"
        onChange={handleImportFile}
      />

      {importError && (
        <p role="alert" className="text-sm text-danger">
          {importError}
        </p>
      )}

      <TabPanel id="list" value={tab}>
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
      </TabPanel>

      <TabPanel id="records" value={tab}>
        <RecordsExplorer scopeLabel="All collections" />
      </TabPanel>
    </Page>
  )
}
