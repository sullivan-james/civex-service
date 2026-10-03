import {
  Badge,
  Button,
  Checkbox,
  Field,
  FormError,
  Input,
  Spinner,
} from '../ui'
import { ArrowLeft, Check } from '../ui/icons'
import { CollectionPicker } from './CollectionPicker'
import { NEW_COLLECTION, type ConfirmState } from './importWizardTypes'
import type { CsvRowPlan, FilePlan, Mode } from './importWizardTypes'
import type { Collection } from '../../api/collections'

/** Step 3: review the dry-run plan, opt into an automation, resolve a
 * collection if the entry point didn't already fix one, and run. */
export function ConfirmStep({
  mode,
  isNewSchema,
  newSchemaName,
  targetSchemaName,
  csvCreateCount,
  csvSkipCount,
  filesCreateCount,
  filesUpdateCount,
  filesSkipCount,
  csvPlan,
  filesPlan,
  showCollectionPicker,
  collections,
  state,
  onChange,
  runErrorBanner,
  running,
  progress,
  total,
  onBack,
  onRun,
}: {
  mode: Mode
  isNewSchema: boolean
  newSchemaName: string
  targetSchemaName: string
  csvCreateCount: number
  csvSkipCount: number
  filesCreateCount: number
  filesUpdateCount: number
  filesSkipCount: number
  csvPlan: CsvRowPlan[]
  filesPlan: FilePlan[]
  showCollectionPicker: boolean
  collections: Collection[] | undefined
  state: ConfirmState
  onChange: (patch: Partial<ConfirmState>) => void
  runErrorBanner: string | null
  running: boolean
  progress: number
  total: number
  onBack: () => void
  onRun: () => void
}) {
  const isNewCollection = state.collectionChoice === NEW_COLLECTION
  const collectionValid = !showCollectionPicker
    ? true
    : isNewCollection
      ? !!state.newCollection.name.trim()
      : !!state.collectionChoice
  const automationValid =
    !state.saveAsAutomation || !!state.automationLabel.trim()
  const canRun = collectionValid && automationValid && !running && total > 0

  return (
    <div className="space-y-5">
      {showCollectionPicker && (
        <CollectionPicker
          collections={collections}
          value={state.collectionChoice}
          onChange={(collectionChoice) => onChange({ collectionChoice })}
          isNew={isNewCollection}
          newCollection={state.newCollection}
          onNewCollectionChange={(newCollection) => onChange({ newCollection })}
        />
      )}

      <div className="border border-border rounded-md p-4 bg-canvas-subtle space-y-2">
        <p className="text-sm text-fg">
          {isNewSchema && (
            <>
              Creates a new record type{' '}
              <Badge variant="accent">{newSchemaName || '(unnamed)'}</Badge>
              .{' '}
            </>
          )}
          {mode === 'csv' ? (
            <>
              <strong>{csvCreateCount}</strong> record
              {csvCreateCount === 1 ? '' : 's'} will be created in{' '}
              <Badge variant="accent">{targetSchemaName}</Badge>.
              {csvSkipCount > 0 && (
                <>
                  {' '}
                  {csvSkipCount} row{csvSkipCount === 1 ? '' : 's'} will be
                  skipped.
                </>
              )}
            </>
          ) : (
            <>
              <strong>{filesCreateCount}</strong> record
              {filesCreateCount === 1 ? '' : 's'} will be created
              {filesUpdateCount > 0 && (
                <>
                  , <strong>{filesUpdateCount}</strong> existing record
                  {filesUpdateCount === 1 ? '' : 's'} will be updated
                </>
              )}{' '}
              in <Badge variant="accent">{targetSchemaName}</Badge>.
              {filesSkipCount > 0 && (
                <>
                  {' '}
                  {filesSkipCount} file{filesSkipCount === 1 ? '' : 's'} will be
                  skipped.
                </>
              )}
            </>
          )}
        </p>

        {(mode === 'csv' ? csvSkipCount : filesSkipCount) > 0 && (
          <details className="text-xs text-fg-muted">
            <summary className="cursor-pointer">View skipped items</summary>
            <ul className="mt-1 space-y-0.5 max-h-40 overflow-y-auto">
              {(mode === 'csv'
                ? csvPlan
                    .filter((p) => p.skip)
                    .map((p) => `Row ${p.index + 1}: ${p.skip}`)
                : filesPlan
                    .filter((p) => p.skip)
                    .map((p) => `${p.file.name}: ${p.skip}`)
              ).map((line, i) => (
                <li key={i} className="font-mono">
                  {line}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>

      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm text-fg cursor-pointer">
          <Checkbox
            checked={state.saveAsAutomation}
            onChange={(e) => onChange({ saveAsAutomation: e.target.checked })}
          />
          Save this as a reusable automation
        </label>
        {state.saveAsAutomation && (
          <div className="pl-3 border-l-2 border-accent-muted space-y-2">
            <Field
              label="Automation name"
              span={6}
              info={
                mode === 'csv'
                  ? `Creates a "${targetSchemaName || 'record'}_import" record type — attach a new CSV to it to repeat this import.`
                  : 'Re-run it later from the Workflows page with a new folder of files.'
              }
            >
              <Input
                size="sm"
                value={state.automationLabel}
                onChange={(e) => onChange({ automationLabel: e.target.value })}
                placeholder={`Import ${targetSchemaName || 'records'}`}
              />
            </Field>
          </div>
        )}
      </div>

      {runErrorBanner && <FormError message={runErrorBanner} />}

      <div className="flex justify-between items-center">
        <Button onClick={onBack} disabled={running}>
          <ArrowLeft size={14} /> Back
        </Button>
        <Button variant="primary" disabled={!canRun} onClick={onRun}>
          {running ? (
            <>
              <Spinner /> Importing {progress}/{total}…
            </>
          ) : (
            <>
              <Check size={14} /> Import {total} record{total === 1 ? '' : 's'}
            </>
          )}
        </Button>
      </div>
    </div>
  )
}
