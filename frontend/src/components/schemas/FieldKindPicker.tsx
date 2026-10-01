import type { FieldKind } from '../../api/schemas'
import { useFieldTypes } from '../../hooks/useFieldTypes'
import { Skeleton } from '../ui'

/** "What kind of data is this?" Starts a new field from what the data is
 * (a quantity, a location, a recording) rather than from a storage type. */
export function FieldKindPicker({
  onPick,
  onCancel,
}: {
  onPick: (kind: FieldKind) => void
  onCancel?: () => void
}) {
  const types = useFieldTypes()
  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-fg">New field</h3>
        <p className="text-xs text-fg-subtle">
          What kind of data will it hold?
        </p>
      </div>
      {!types ? (
        <Skeleton className="h-32 w-full" />
      ) : (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {types.kinds.map((k) => (
            <li key={k.key}>
              <button
                type="button"
                onClick={() => onPick(k)}
                className="flex h-full w-full flex-col items-start gap-0.5 rounded-md border border-border bg-canvas px-3 py-2 text-left hover:border-accent hover:bg-accent-subtle cursor-pointer"
              >
                <span className="text-sm font-medium text-fg">{k.label}</span>
                <span className="text-xs text-fg-muted">{k.description}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {onCancel && (
        <button
          type="button"
          onClick={onCancel}
          className="text-xs text-accent hover:underline cursor-pointer"
        >
          Cancel
        </button>
      )}
    </div>
  )
}
