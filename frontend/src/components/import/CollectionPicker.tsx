import { Field, Input, Select } from '../ui'
import { NEW_COLLECTION } from './importWizardTypes'
import type { Collection } from '../../api/collections'

/** "Which collection" chooser — the collection-choice counterpart to
 * SchemaPicker, for entry points (e.g. the schema page) that don't already
 * know one. Same pick-existing-or-create-inline shape; the actual
 * collection isn't created until the caller runs the import, same as a
 * newly-drafted schema. */
export function CollectionPicker({
  collections,
  value,
  onChange,
  isNew,
  newCollection,
  onNewCollectionChange,
}: {
  collections: Collection[] | undefined
  value: string
  onChange: (collectionChoice: string) => void
  isNew: boolean
  newCollection: { name: string; description: string }
  onNewCollectionChange: (next: { name: string; description: string }) => void
}) {
  return (
    <div className="space-y-2">
      <span className="text-xs font-semibold text-fg-muted uppercase tracking-wide">
        Collection
      </span>
      <Select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full max-w-sm"
      >
        <option value="">— Select a collection —</option>
        <option value={NEW_COLLECTION}>+ Create a new collection</option>
        {collections?.map((c) => (
          <option key={c.name} value={c.name}>
            {c.name}
          </option>
        ))}
      </Select>
      {isNew && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 pt-2">
          <Field label="Name">
            <Input
              autoFocus
              value={newCollection.name}
              onChange={(e) =>
                onNewCollectionChange({
                  ...newCollection,
                  name: e.target.value,
                })
              }
              placeholder="my-collection"
            />
          </Field>
          <Field label="Description">
            <Input
              value={newCollection.description}
              onChange={(e) =>
                onNewCollectionChange({
                  ...newCollection,
                  description: e.target.value,
                })
              }
              placeholder="Optional"
            />
          </Field>
        </div>
      )}
    </div>
  )
}
