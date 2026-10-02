import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import type { Field as SchemaField } from '../api/schemas'
import { useCollection } from '../hooks/useCollections'
import { UploadCollectionContext } from '../hooks/uploadCollection'
import { useCreateRecord, useRecord } from '../hooks/useRecords'
import { useSchemas } from '../hooks/useSchemas'
import {
  Badge,
  Button,
  DetailSkeleton,
  ErrorState,
  Page,
  Section,
} from '../components/ui'
import { CollectionTimeZone } from '../components/records/CollectionTimeZone'
import { RecordPageFrame } from '../components/records/RecordPageFrame'
import { fieldSaveErrors } from '../components/records/saveErrors'
import { recordTrail } from '../utils/recordTrail'
import { RecordFieldGrid } from '../components/records/RecordFieldGrid'
import {
  FilenameExtractor,
  EXTRACTABLE_TYPES,
  collectFileSources,
} from '../components/records/FilenameExtractor'
import { ScanText } from '../components/ui/icons'
import { displayLabel } from '../utils/naming'
import { errorMessage } from '../lib/errors'

const PARENT = '__parent__'

/** A new record, laid out exactly like an existing one: the same field rows,
 * all blank, edited in place. Nothing is saved until "Add". Reached from a
 * list's "Add" button, with `?schema=` (what to add) and `?parent=` (the
 * record it goes under, when the list was scoped to one). */
export default function NewRecordPage() {
  const { id } = useParams<{ id: string }>()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const schemaName = params.get('schema')
  const parentParam = params.get('parent')
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [extracting, setExtracting] = useState<string | null>(null)

  const { data: collection, isLoading, error } = useCollection(id!)
  const { data: schemas } = useSchemas()
  const { data: parentRecord } = useRecord(parentParam)
  const createRecord = useCreateRecord(collection?.name ?? '')

  const schema = schemas?.find((s) => s.name === schemaName)
  const parentSchema = schema?.parent_id
    ? schemas?.find((s) => s.id === schema.parent_id)
    : undefined

  // Choosing the parent is one more row, above the schema's own fields --
  // unless the list this came from already fixed it.
  const parentField = useMemo<SchemaField | null>(
    () =>
      parentSchema && !parentParam
        ? {
            id: PARENT,
            name: PARENT,
            label: `Parent ${displayLabel(parentSchema.name, parentSchema.label)}`,
            type: 'reference',
            required: true,
            restrictions: { schema: parentSchema.name },
            default: null,
            position: -1,
          }
        : null,
    [parentSchema, parentParam],
  )

  const listHref = `/collections/${id}${
    schemaName
      ? `?${new URLSearchParams({
          schema: schemaName,
          ...(parentParam ? { within: parentParam } : {}),
        })}`
      : ''
  }`
  const parentPath = parentRecord
    ? [...(parentRecord.ancestors ?? []), parentRecord]
    : []
  const breadcrumbs = recordTrail(collection, parentPath)

  if (isLoading || !schemas)
    return (
      <Page
        breadcrumbs={breadcrumbs}
        loading={<DetailSkeleton metadataRows={4} sections={1} />}
      />
    )
  if (error || !collection || !schema)
    return (
      <Page
        breadcrumbs={breadcrumbs}
        error={
          <ErrorState
            message={
              error
                ? errorMessage(error)
                : !collection
                  ? 'Collection not found'
                  : 'Unknown schema'
            }
          />
        }
      />
    )

  const label = displayLabel(schema.name, schema.label)
  const fields = parentField ? [parentField, ...schema.fields] : schema.fields
  const fileSources = collectFileSources(values, schema.fields)
  // Anything the server didn't pin to a field goes on the first row, where
  // it is seen alongside the Add button.
  const errors = fieldSaveErrors(
    createRecord.error,
    schema.fields.map((f) => f.name),
    fields[0]?.name ?? PARENT,
  )

  function submit() {
    const data: Record<string, unknown> = {}
    for (const f of schema!.fields)
      if (values[f.name] !== undefined) data[f.name] = values[f.name]
    createRecord.mutate(
      {
        schema_name: schema!.name,
        data,
        parent_record_id:
          parentParam ?? (values[PARENT] as string | undefined) ?? undefined,
      },
      { onSuccess: (created) => navigate(`/records/${created.id}`) },
    )
  }

  return (
    <CollectionTimeZone
      timeZone={collection.timezone}
      collection={collection.name}
    >
      <RecordPageFrame
        collection={collection.name}
        collectionId={id!}
        path={parentPath}
        current={`New ${label.toLowerCase()}`}
        title={
          <span className="inline-flex items-center gap-2">
            New {label.toLowerCase()}
            <Badge variant="accent">{schema.name}</Badge>
          </span>
        }
        description="Fill in what you have — click a value to edit it. Nothing is saved until you add the record."
      >
        <UploadCollectionContext.Provider value={collection.id}>
          <Section title="Fields">
            <RecordFieldGrid
              fields={fields}
              data={values}
              onSave={(name, value) =>
                setValues((prev) => {
                  const next = { ...prev }
                  if (value === undefined) delete next[name]
                  else next[name] = value
                  return next
                })
              }
              errors={errors}
              onDismissError={() => createRecord.reset()}
              extra={(field) => {
                if (
                  field.name === PARENT ||
                  !EXTRACTABLE_TYPES.has(field.type) ||
                  fileSources.length === 0
                )
                  return null
                const open = extracting === field.name
                return (
                  <>
                    <button
                      type="button"
                      onClick={() => setExtracting(open ? null : field.name)}
                      className="mt-1 inline-flex items-center gap-1 text-xs text-fg-muted hover:text-accent cursor-pointer"
                    >
                      <ScanText size={11} /> fill from filename
                    </button>
                    {open && (
                      <FilenameExtractor
                        sources={fileSources}
                        fieldType={field.type}
                        onApply={(v) =>
                          setValues((prev) => ({ ...prev, [field.name]: v }))
                        }
                        onClose={() => setExtracting(null)}
                      />
                    )}
                  </>
                )
              }}
            />
          </Section>
        </UploadCollectionContext.Provider>
        <div className="flex gap-2">
          <Button
            variant="primary"
            onClick={submit}
            disabled={
              createRecord.isPending || (!!parentField && !values[PARENT])
            }
          >
            {createRecord.isPending ? 'Adding…' : `Add ${label.toLowerCase()}`}
          </Button>
          <Link to={listHref}>
            <Button>Cancel</Button>
          </Link>
        </div>
      </RecordPageFrame>
    </CollectionTimeZone>
  )
}
