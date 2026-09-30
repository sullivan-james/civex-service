import { useEffect, useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router'
import { Upload } from '../components/ui/icons'
import {
  useCollection,
  useUpdateCollection,
  useDeleteCollection,
} from '../hooks/useCollections'
import {
  Button,
  CollapsibleSection,
  ConfirmDialog,
  DetailSkeleton,
  Badge,
  ErrorState,
  Field,
  Input,
  Page,
  TableSkeleton,
} from '../components/ui'
import { recordCollectionVisit } from '../hooks/useFrequentCollections'
import { RecordsExplorer } from '../components/explorer/RecordsExplorer'
import { WithHierarchy } from '../components/explorer/HierarchySidebar'
import { AuditTrail } from '../components/audit/AuditTrail'
import { collectionsApi } from '../api/collections'
import { describeAuditEntry as describeCollectionAuditEntry } from '../utils/collectionAudit'
import { errorMessage } from '../lib/errors'
import { HIGH_IMPACT_RECORD_THRESHOLD } from '../lib/deleteImpact'

/** A collection is a workspace over its records: the explorer does all the
 * browsing (hierarchy, search, filters, bulk actions); this page adds the
 * collection's own details and lifecycle around it. */
export default function CollectionDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [editing, setEditing] = useState(false)
  const [nameValue, setNameValue] = useState('')
  const [descriptionValue, setDescriptionValue] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)

  const { data: collection, isLoading, error } = useCollection(id!)
  const collectionName = collection?.name
  useEffect(() => {
    if (collectionName) recordCollectionVisit(collectionName)
  }, [collectionName])
  const updateCollection = useUpdateCollection()
  const deleteCollection = useDeleteCollection()

  const breadcrumbs = [{ label: 'Collections', to: '/collections' }]

  if (isLoading)
    return (
      <Page
        breadcrumbs={breadcrumbs}
        loading={
          <>
            <DetailSkeleton metadataRows={0} sections={0} />
            <TableSkeleton
              columns={['w-8', 'w-20', 'w-32', 'w-32', 'w-24']}
              rows={8}
            />
          </>
        }
      />
    )
  if (error || !collection)
    return (
      <Page
        breadcrumbs={breadcrumbs}
        error={
          <ErrorState
            message={error ? errorMessage(error) : 'Collection not found'}
          />
        }
      />
    )

  function startEditing() {
    setNameValue(collection!.name)
    setDescriptionValue(collection!.description ?? '')
    setEditing(true)
  }

  function handleSaveEdit() {
    const newName = nameValue.trim()
    const body: { rename?: string; description?: string } = {}
    if (newName && newName !== collection!.name) body.rename = newName
    if (descriptionValue !== (collection!.description ?? ''))
      body.description = descriptionValue
    if (!Object.keys(body).length) {
      setEditing(false)
      return
    }
    updateCollection.mutate(
      { name: collection!.name, body },
      { onSuccess: () => setEditing(false) },
    )
  }

  const recordCount = collection.record_count

  return (
    <WithHierarchy dataset={collection.name} collectionId={id}>
      <Page
        breadcrumbs={[...breadcrumbs, { label: collection.name }]}
        title={
          <span className="inline-flex flex-wrap items-center gap-3">
            {collection.name}
            <Badge variant="accent">
              {recordCount.toLocaleString()}{' '}
              {recordCount === 1 ? 'record' : 'records'}
            </Badge>
          </span>
        }
        description={collection.description ?? undefined}
        action={
          <Link to={`/collections/${id}/import`}>
            <Button size="sm" variant="primary">
              <Upload size={14} /> Guided import
            </Button>
          </Link>
        }
        secondaryActions={[
          { label: 'Edit details', onClick: startEditing },
          {
            label: 'Delete collection',
            variant: 'danger',
            onClick: () => setConfirmDelete(true),
          },
        ]}
      >
        {editing && (
          <div className="border border-border rounded-md p-4 bg-canvas-subtle flex flex-col gap-3">
            <Field label="Collection name">
              <Input
                autoFocus
                value={nameValue}
                onChange={(e) => setNameValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleSaveEdit()
                  if (e.key === 'Escape') setEditing(false)
                }}
              />
            </Field>
            <Field label="Description">
              <Input
                value={descriptionValue}
                onChange={(e) => setDescriptionValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') setEditing(false)
                }}
                placeholder="No description"
              />
            </Field>
            {updateCollection.error && (
              <span role="alert" className="text-xs text-danger">
                {errorMessage(updateCollection.error)}
              </span>
            )}
            <div className="flex gap-2">
              <Button
                variant="primary"
                size="sm"
                onClick={handleSaveEdit}
                disabled={updateCollection.isPending || !nameValue.trim()}
              >
                {updateCollection.isPending ? 'Saving…' : 'Save'}
              </Button>
              <Button size="sm" onClick={() => setEditing(false)}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        <RecordsExplorer
          dataset={collection.name}
          scopeLabel={collection.name}
          emptyHint={
            <>
              Add your first record with the button above, or use{' '}
              <Link
                to={`/collections/${id}/import`}
                className="text-accent hover:underline"
              >
                guided import
              </Link>{' '}
              to bring in a folder of files or a spreadsheet.
            </>
          }
        />

        <CollapsibleSection title="Activity">
          <AuditTrail
            queryKey={['collections', collection.name, 'audit']}
            fetchPage={(offset, limit) =>
              collectionsApi.getAudit(collection.name, offset, limit)
            }
            describeEntry={describeCollectionAuditEntry}
            emptyMessage="Changes to this collection will appear here."
          />
        </CollapsibleSection>

        {confirmDelete && (
          <ConfirmDialog
            title="Delete collection"
            body={
              recordCount > 0
                ? `Delete "${collection.name}"? This moves it and its ${recordCount.toLocaleString()} record(s) to Recently Deleted — restore any time before it's permanently purged.`
                : `Delete "${collection.name}"? It has no records. It moves to Recently Deleted — restore any time before it's permanently purged.`
            }
            confirmLabel={
              recordCount > 0
                ? `Delete collection and ${recordCount.toLocaleString()} record${recordCount === 1 ? '' : 's'}`
                : 'Delete collection'
            }
            variant="danger"
            typedConfirmationValue={
              recordCount > HIGH_IMPACT_RECORD_THRESHOLD
                ? collection.name
                : undefined
            }
            warning={
              deleteCollection.error
                ? errorMessage(deleteCollection.error)
                : undefined
            }
            isPending={deleteCollection.isPending}
            onConfirm={() =>
              deleteCollection.mutate(collection.name, {
                onSuccess: () => navigate('/collections'),
              })
            }
            onClose={() => setConfirmDelete(false)}
          />
        )}
      </Page>
    </WithHierarchy>
  )
}
