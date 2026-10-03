import { Badge, Button, Checkbox, Field, InfoTip, Select } from '../ui'
import { ArrowLeft, ArrowRight } from '../ui/icons'
import { RecordSearchPicker } from '../records/RecordSearchPicker'
import { displayLabel } from '../../utils/naming'
import { NewFieldEditor } from './NewFieldEditor'
import { SchemaPicker } from './SchemaPicker'
import {
  FilenamePatternPreview,
  type ExtractOutputType,
} from './FilenamePatternPreview'
import { NEW_FIELD, SKIP_COLUMN, type MapState } from './importWizardTypes'
import { UNIT_GROUPS, dimensionOf } from '../../utils/units'
import type { ParsedCsv } from '../../utils/csv'
import type { Schema, Field as SchemaField } from '../../api/schemas'
import type { Mode, Strategy } from './importWizardTypes'

/** Step 2: which record type, which field(s), and (for files) how to
 * strategise. Renders SchemaPicker itself only when the schema wasn't
 * already fixed by the entry point (e.g. entering from the schema page). */
export function MapStep({
  mode,
  state,
  onChange,
  showSchemaPicker,
  schemas,
  isNewSchema,
  onSchemaChoiceChange,
  availableFields,
  availableFileFields,
  availableNonFileFields,
  targetSchemaName,
  needsParent,
  parentSchema,
  hasParentCandidates,
  parsedCsv,
  collectionTimeZone,
  canMatch,
  strategy,
  filenames,
  extraOutputType,
  mapValid,
  onBack,
  onContinue,
}: {
  mode: Mode
  state: MapState
  onChange: (patch: Partial<MapState>) => void
  showSchemaPicker: boolean
  schemas: Schema[] | undefined
  isNewSchema: boolean
  onSchemaChoiceChange: (schemaChoice: string) => void
  availableFields: SchemaField[]
  availableFileFields: SchemaField[]
  availableNonFileFields: SchemaField[]
  targetSchemaName: string
  needsParent: boolean
  parentSchema: Schema | null
  hasParentCandidates: boolean
  parsedCsv: ParsedCsv | null
  /** Timezone of the collection being imported into: a zone name, null when
   * the collection has none, undefined when it isn't chosen yet. */
  collectionTimeZone?: string | null
  canMatch: boolean
  strategy: Strategy
  filenames: string[]
  extraOutputType: ExtractOutputType
  mapValid: boolean
  onBack: () => void
  onContinue: () => void
}) {
  // Is any CSV column headed for a datetime field? (existing, or new)
  const hasDatetimeColumn =
    mode === 'csv' &&
    Object.entries(state.columnMap).some(([col, target]) =>
      target === NEW_FIELD
        ? state.newColumnFields[col]?.type === 'datetime'
        : availableFields.find((f) => f.name === target)?.type === 'datetime',
    )

  return (
    <div className="space-y-5">
      {showSchemaPicker && (
        <SchemaPicker
          schemas={schemas}
          value={state.schemaChoice}
          onChange={onSchemaChoiceChange}
          isNew={isNewSchema}
          newSchema={state.newSchema}
          onNewSchemaChange={(newSchema) => onChange({ newSchema })}
        />
      )}

      {needsParent && parentSchema && (
        <div className="space-y-1">
          <span className="text-xs font-semibold text-fg-muted uppercase tracking-wide flex items-center gap-2">
            Parent record
            <Badge variant="accent">
              {displayLabel(parentSchema.name, parentSchema.label)}
            </Badge>
          </span>
          {!hasParentCandidates ? (
            <p className="text-xs text-danger">
              No {displayLabel(parentSchema.name, parentSchema.label)} records
              yet — add one first.
            </p>
          ) : (
            <RecordSearchPicker
              schemaName={parentSchema.name}
              value={state.parentRecordId || undefined}
              onChange={(id) => onChange({ parentRecordId: id ?? '' })}
              placeholder="Search records…"
              className="w-full max-w-sm"
            />
          )}
        </div>
      )}

      {mode === 'csv' && parsedCsv && (
        <div className="space-y-1">
          <span className="flex items-center gap-1 text-sm font-medium text-fg">
            Column mapping
            {hasDatetimeColumn && (
              <InfoTip>
                {collectionTimeZone
                  ? `Times without a UTC offset are read as ${collectionTimeZone}.`
                  : collectionTimeZone === null
                    ? 'This collection has no timezone, so times without a UTC offset are read as UTC. Set one on the collection to change that.'
                    : "Times without a UTC offset are read in the chosen collection's timezone (UTC if it has none)."}{' '}
                A field can override this in its settings.
              </InfoTip>
            )}
          </span>
          <div className="border border-border rounded-md divide-y divide-border-muted">
            {parsedCsv.columns.map((col) => (
              <div key={col} className="px-3 py-2">
                <div className="flex items-center gap-3">
                  <span
                    className="text-sm text-fg font-mono truncate flex-1"
                    title={col}
                  >
                    {col}
                  </span>
                  <ArrowRight size={12} className="text-fg-subtle shrink-0" />
                  <Select
                    size="sm"
                    value={state.columnMap[col] ?? SKIP_COLUMN}
                    onChange={(e) =>
                      onChange({
                        columnMap: {
                          ...state.columnMap,
                          [col]: e.target.value,
                        },
                      })
                    }
                    className="w-56 shrink-0"
                  >
                    <option value={SKIP_COLUMN}>— Skip this column —</option>
                    <option value={NEW_FIELD}>+ Create new field</option>
                    {availableFields
                      .filter(
                        (f) => f.type !== 'file' && f.type !== 'file_list',
                      )
                      .map((f) => (
                        <option key={f.name} value={f.name}>
                          {displayLabel(f.name, f.label)}
                        </option>
                      ))}
                  </Select>
                </div>
                {(() => {
                  const target = availableFields.find(
                    (f) => f.name === state.columnMap[col],
                  )
                  const fieldUnit =
                    target?.type === 'float' &&
                    typeof target.restrictions?.unit === 'string'
                      ? target.restrictions.unit
                      : null
                  const dimension = fieldUnit ? dimensionOf(fieldUnit) : null
                  if (!fieldUnit || !dimension) return null
                  return (
                    <label className="mt-2 flex items-center gap-2 text-xs text-fg-muted">
                      Values in this column are in
                      <Select
                        size="sm"
                        value={state.columnUnits[col] ?? fieldUnit}
                        onChange={(e) =>
                          onChange({
                            columnUnits: {
                              ...state.columnUnits,
                              [col]: e.target.value,
                            },
                          })
                        }
                        className="w-28"
                      >
                        {UNIT_GROUPS[dimension].map((u) => (
                          <option key={u} value={u}>
                            {u}
                          </option>
                        ))}
                      </Select>
                      {(state.columnUnits[col] ?? fieldUnit) !== fieldUnit && (
                        <span>converted to {fieldUnit} on import</span>
                      )}
                    </label>
                  )
                })()}
                {state.columnMap[col] === NEW_FIELD &&
                  state.newColumnFields[col] && (
                    <NewFieldEditor
                      draft={state.newColumnFields[col]}
                      onChange={(next) =>
                        onChange({
                          newColumnFields: {
                            ...state.newColumnFields,
                            [col]: next,
                          },
                        })
                      }
                    />
                  )}
              </div>
            ))}
          </div>
        </div>
      )}

      {mode === 'files' && (
        <div className="space-y-5">
          <div className="space-y-1">
            <span className="text-xs font-semibold text-fg-muted uppercase tracking-wide">
              Store each file in
            </span>
            <Select
              value={state.fileFieldChoice}
              onChange={(e) => onChange({ fileFieldChoice: e.target.value })}
              className="w-full max-w-sm"
            >
              <option value="">— Select a field —</option>
              <option value={NEW_FIELD}>+ Create new field</option>
              {availableFileFields.map((f) => (
                <option key={f.name} value={f.name}>
                  {displayLabel(f.name, f.label)}
                </option>
              ))}
            </Select>
            {state.fileFieldChoice === NEW_FIELD && (
              <NewFieldEditor
                draft={state.newFileField}
                onChange={(newFileField) => onChange({ newFileField })}
                typeOptions={['file']}
              />
            )}
          </div>

          <div className="space-y-2">
            <span className="text-xs font-semibold text-fg-muted uppercase tracking-wide">
              Strategy
            </span>
            <div className="flex flex-col gap-2">
              <label className="flex items-start gap-2 text-sm text-fg cursor-pointer">
                <input
                  type="radio"
                  className="mt-1"
                  checked={state.strategyChoice === 'create'}
                  onChange={() => onChange({ strategyChoice: 'create' })}
                />
                <span>
                  Create one record per file
                  <span className="block text-xs text-fg-muted">
                    Every file becomes a new {targetSchemaName || 'record'}.
                  </span>
                </span>
              </label>
              <label
                className={`flex items-start gap-2 text-sm cursor-pointer ${canMatch ? 'text-fg' : 'text-fg-subtle cursor-not-allowed'}`}
              >
                <input
                  type="radio"
                  className="mt-1"
                  disabled={!canMatch}
                  checked={state.strategyChoice === 'match'}
                  onChange={() => onChange({ strategyChoice: 'match' })}
                />
                <span>
                  Match to existing records by a key in the filename
                  <span className="block text-xs text-fg-muted">
                    {canMatch
                      ? 'Update the matching record, or create one if no key matches.'
                      : 'Only available for a record type that is a child of another record.'}
                  </span>
                </span>
              </label>
            </div>
          </div>

          {strategy === 'match' && (
            <div className="space-y-2 pl-3 border-l-2 border-accent-muted">
              <Field label="Match against field" span={6}>
                <Select
                  size="sm"
                  value={state.keyFieldName}
                  onChange={(e) => onChange({ keyFieldName: e.target.value })}
                >
                  <option value="">— Select a field —</option>
                  {availableNonFileFields.map((f) => (
                    <option key={f.name} value={f.name}>
                      {displayLabel(f.name, f.label)}
                    </option>
                  ))}
                </Select>
              </Field>
              <FilenamePatternPreview
                filenames={filenames}
                pattern={state.pattern}
                onPatternChange={(pattern) => onChange({ pattern })}
                outputType="string"
                dateFormat=""
                onDateFormatChange={() => {}}
              />
            </div>
          )}

          {strategy === 'create' && (
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm text-fg cursor-pointer">
                <Checkbox
                  checked={state.extraExtractEnabled}
                  onChange={(e) =>
                    onChange({ extraExtractEnabled: e.target.checked })
                  }
                />
                Also fill a field from the filename
              </label>
              {state.extraExtractEnabled && (
                <div className="space-y-2 pl-3 border-l-2 border-accent-muted">
                  <Field label="Target field" span={6}>
                    <Select
                      size="sm"
                      value={state.extraFieldChoice}
                      onChange={(e) =>
                        onChange({ extraFieldChoice: e.target.value })
                      }
                    >
                      <option value="">— Select a field —</option>
                      <option value={NEW_FIELD}>+ Create new field</option>
                      {availableNonFileFields.map((f) => (
                        <option key={f.name} value={f.name}>
                          {displayLabel(f.name, f.label)}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  {state.extraFieldChoice === NEW_FIELD && (
                    <NewFieldEditor
                      draft={state.newExtraField}
                      onChange={(newExtraField) => onChange({ newExtraField })}
                    />
                  )}
                  <FilenamePatternPreview
                    filenames={filenames}
                    pattern={state.pattern}
                    onPatternChange={(pattern) => onChange({ pattern })}
                    outputType={extraOutputType}
                    dateFormat=""
                    onDateFormatChange={() => {}}
                  />
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <div className="flex justify-between">
        <Button onClick={onBack}>
          <ArrowLeft size={14} /> Back
        </Button>
        <Button variant="primary" disabled={!mapValid} onClick={onContinue}>
          Continue <ArrowRight size={14} />
        </Button>
      </div>
    </div>
  )
}
