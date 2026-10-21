import type { FieldKind } from '../../api/schemas'
import { useFieldTypes } from '../../hooks/useFieldTypes'
import { Button, Card, Skeleton } from '../ui'

/** "What kind of field?" Starts a new field from what the data is (a
 * quantity, a location, a file) rather than from a storage type. One big
 * card per kind, so the choice is read and pressed, not studied. */
export function FieldKindPicker({
  onPick,
  onCancel,
  title = 'What kind of field?',
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
        <Skeleton className="h-40 w-full" />
      ) : (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {types.kinds.map((k) => (
            <li key={k.key}>
              <Card
                onClick={() => onPick(k)}
                className="h-full min-h-20 px-4 py-4"
              >
                <span className="block text-base font-medium text-fg">
                  {k.label}
                </span>
                <span className="mt-1 block text-sm text-fg-muted">
                  {k.description}
                </span>
              </Card>
            </li>
          ))}
        </ul>
      )}
      {onCancel && (
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      )}
    </div>
  )
}
