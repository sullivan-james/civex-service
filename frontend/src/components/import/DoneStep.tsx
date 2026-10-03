import { Link } from 'react-router'
import { Badge, Button, FormError } from '../ui'
import { recordLabel } from '../records/RecordSearchPicker'
import type { ImportOutcome } from './importWizardTypes'

/** Step 4: what happened, and where to go next. `doneHref` is
 * context-aware — the collection just imported into, when the wizard
 * picked or created one, otherwise wherever the entry point came from
 * (e.g. the schema page). */
export function DoneStep({
  result,
  doneHref,
  onImportMore,
}: {
  result: ImportOutcome
  doneHref: string
  onImportMore: () => void
}) {
  return (
    <div className="space-y-5">
      <div className="border border-success-muted bg-success-subtle rounded-md p-4">
        <p className="text-sm text-success font-medium">
          {result.created.length} created
          {result.updated.length > 0 && `, ${result.updated.length} updated`}
          {result.skipped.length > 0 && `, ${result.skipped.length} skipped`}
        </p>
      </div>

      {result.automationError && (
        <FormError
          message={`Import finished, but saving the automation failed: ${result.automationError}`}
        />
      )}
      {result.automationStem && (
        <p className="text-sm text-fg">
          Saved as automation —{' '}
          <Link
            to={`/workflows/${encodeURIComponent(result.automationStem)}`}
            className="text-accent hover:underline"
          >
            view "{result.automationStem}"
          </Link>
        </p>
      )}

      {(result.created.length > 0 || result.updated.length > 0) && (
        <div className="border border-border rounded-md">
          <div className="px-3 py-2 text-xs font-medium text-fg-muted bg-canvas-subtle border-b border-border">
            Records
          </div>
          <div className="max-h-72 overflow-y-auto divide-y divide-border-muted">
            {[...result.created, ...result.updated].map((r) => (
              <Link
                key={r.id}
                to={`/records/${r.id}`}
                className="flex items-center justify-between px-3 py-1.5 text-sm text-accent hover:bg-canvas-subtle hover:underline"
              >
                <span>{recordLabel(r)}</span>
                <Badge
                  variant={result.created.includes(r) ? 'success' : 'default'}
                >
                  {result.created.includes(r) ? 'created' : 'updated'}
                </Badge>
              </Link>
            ))}
          </div>
        </div>
      )}

      {result.skipped.length > 0 && (
        <details className="text-xs text-fg-muted border border-border rounded-md p-3">
          <summary className="cursor-pointer font-medium text-fg">
            {result.skipped.length} skipped
          </summary>
          <ul className="mt-2 space-y-0.5 max-h-40 overflow-y-auto">
            {result.skipped.map((s, i) => (
              <li key={i} className="font-mono">
                {s.label}: {s.reason}
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="flex gap-2">
        <Button to={doneHref} variant="primary">
          Done
        </Button>
        <Button onClick={onImportMore}>Import more</Button>
      </div>
    </div>
  )
}
