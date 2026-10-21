import type { FieldKind } from '../../api/schemas'
import { useFieldTypes } from '../../hooks/useFieldTypes'
import { Button, Card, Skeleton } from '../ui'

/** "What kind of data is this?" Starts a new field from what the data is
 * (a quantity, a location, a recording) rather than from a storage type. */
export function FieldKindPicker({
  onPick,
  onCancel,
  title = 'New field',
}: {
  onPick: (kind: FieldKind) => void
  onCancel?: () => void
  /** The heading; null when the surround already has one. */
  title?: string | null
}) {
  const types = useFieldTypes()
  return (
    <div className="space-y-4">
      {title && <h3 className="text-base font-semibold text-fg">{title}</h3>}
      {!types ? (
        <Skeleton className="h-32 w-full" />
      ) : (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {types.kinds.map((k) => (
            <li key={k.key}>
              <Card onClick={() => onPick(k)} className="h-full px-3 py-3">
                <span className="block text-sm font-medium text-fg">
                  {k.label}
                </span>
                <span className="block text-xs text-fg-muted">
                  {k.description}
                </span>
              </Card>
            </li>
          ))}
        </ul>
      )}
      {onCancel && (
        <Button size="sm" variant="link" onClick={onCancel}>
          Cancel
        </Button>
      )}
    </div>
  )
}
