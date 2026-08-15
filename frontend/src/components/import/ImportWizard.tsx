import { useState } from 'react'
import { Link } from 'react-router'
import { useSchemas } from '../../hooks/useSchemas'
import { useRecords } from '../../hooks/useRecords'
import {
  schemasApi,
  type Schema,
  type Field as SchemaField,
} from '../../api/schemas'
import { recordsApi, type CivexRecord } from '../../api/records'
import { RecordSearchPicker } from '../records/RecordSearchPicker'
import { filesApi } from '../../api/files'
import { workflowsApi } from '../../api/workflows'
import {
  Badge,
  Button,
  Checkbox,
  Field,
  FormError,
  Input,
  NameLabelFields,
  Select,
} from '../ui'
import { ArrowLeft, ArrowRight, Check, Upload, Database } from '../ui/icons'
import { parseCsv, type ParsedCsv } from '../../utils/csv'
import {
  inferColumnType,
  suggestFieldMapping,
  type InferredFieldType,
} from '../../utils/importMapping'
import { normalizeNumericKey } from '../../utils/filenamePattern'
import {
  FilenamePatternPreview,
  extractFromFilename,
  type ExtractOutputType,
} from './FilenamePatternPreview'
import {
  buildCsvImportWorkflowYaml,
  buildFilesImportWorkflowYaml,
} from '../../utils/workflowYaml'
import { displayLabel, nameError, slugify } from '../../utils/naming'
import { errorMessage } from '../../lib/errors'

interface Props {
  datasetName: string
}

type Mode = 'files' | 'csv'
type WizardStep = 'source' | 'map' | 'confirm' | 'done'
type Strategy = 'create' | 'match'

interface NewFieldDraft {
  name: string
  label: string
  type: string
}

const SCALAR_TYPES: InferredFieldType[] = [
  'string',
  'integer',
  'float',
  'boolean',
  'date',
  'datetime',
]

const NEW_SCHEMA = '__new__'
const NEW_FIELD = '__new__'
const SKIP_COLUMN = '__skip__'

function Spinner() {
  return (
    <svg
      className="animate-spin"
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      aria-hidden
    >
      <path
        d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"
        strokeLinecap="round"
      />
    </svg>
  )
}

/** Compact inline editor for a not-yet-created field — name/label/type. */
function NewFieldEditor({
  draft,
  onChange,
  typeOptions,
}: {
  draft: NewFieldDraft
  onChange: (next: NewFieldDraft) => void
  typeOptions: readonly string[]
}) {
  const error = draft.name ? nameError(draft.name) : 'A name is required'
  return (
    <div className="flex flex-wrap items-end gap-2 mt-1 pl-3 border-l-2 border-accent-muted">
      <Field label="Label" hideLabel span={4}>
        <Input
          size="sm"
          value={draft.label}
          onChange={(e) =>
            onChange({
              ...draft,
              label: e.target.value,
              name: slugify(e.target.value),
            })
          }
          placeholder="Field label"
        />
      </Field>
      <Field label="Name" hideLabel span={4} error={error ?? undefined}>
        <Input
          size="sm"
          className="font-mono"
          value={draft.name}
          onChange={(e) => onChange({ ...draft, name: e.target.value })}
          placeholder="field_name"
        />
      </Field>
      <Field label="Type" hideLabel span={4}>
        <Select
          size="sm"
          value={draft.type}
          onChange={(e) => onChange({ ...draft, type: e.target.value })}
        >
          {typeOptions.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </Select>
      </Field>
    </div>
  )
}

interface CsvRowPlan {
  index: number
  data: Record<string, unknown>
  skip: string | null
}

interface FilePlan {
  file: File
  data: Record<string, unknown>
  matchedRecord: CivexRecord | null
  skip: string | null
}

interface ImportOutcome {
  created: CivexRecord[]
  updated: CivexRecord[]
  skipped: { label: string; reason: string }[]
  automationStem?: string
  automationError?: string
}

function coerceCsvValue(
  raw: string,
  dtype: string,
): { value: unknown; error: string | null } {
  const trimmed = raw.trim()
  if (trimmed === '') return { value: undefined, error: null }
  if (dtype === 'integer') {
    const n = parseInt(trimmed, 10)
    return isNaN(n)
      ? { value: undefined, error: `"${raw}" is not an integer` }
      : { value: n, error: null }
  }
  if (dtype === 'float') {
    const n = parseFloat(trimmed)
    return isNaN(n)
      ? { value: undefined, error: `"${raw}" is not a number` }
      : { value: n, error: null }
  }
  if (dtype === 'boolean') {
    return {
      value: ['true', 'yes', '1'].includes(trimmed.toLowerCase()),
      error: null,
    }
  }
  return { value: trimmed, error: null }
}

function recordLabel(r: CivexRecord): string {
  return r.natural_name ?? r.id.slice(0, 8)
}

export default function ImportWizard({ datasetName }: Props) {
  const [step, setStep] = useState<WizardStep>('source')
  const [mode, setMode] = useState<Mode | null>(null)

  // ── Source ────────────────────────────────────────────────────────────
  const [files, setFiles] = useState<File[]>([])
  const [csvReadError, setCsvReadError] = useState<string | null>(null)
  const [parsedCsv, setParsedCsv] = useState<ParsedCsv | null>(null)

  async function handleCsvFileChange(file: File | null) {
    setCsvReadError(null)
    setParsedCsv(null)
    if (!file) return
    try {
      const text = await file.text()
      const parsed = parseCsv(text)
      setParsedCsv(parsed)
      applyColumnSuggestions(parsed, availableFields)
    } catch (e) {
      setCsvReadError(errorMessage(e))
    }
  }

  // ── Schema ────────────────────────────────────────────────────────────
  const { data: schemas } = useSchemas()
  const [schemaChoice, setSchemaChoice] = useState<string>('')
  const [newSchema, setNewSchema] = useState({ label: '', name: '' })
  const isNewSchema = schemaChoice === NEW_SCHEMA
  const effectiveSchema: Schema | null = isNewSchema
    ? null
    : (schemas?.find((s) => s.id === schemaChoice) ?? null)
  const targetSchemaName = isNewSchema
    ? newSchema.name
    : (effectiveSchema?.name ?? '')
  const availableFields = effectiveSchema?.fields ?? []
  const availableFileFields = availableFields.filter((f) => f.type === 'file')
  const availableNonFileFields = availableFields.filter(
    (f) => f.type !== 'file' && f.type !== 'file_list',
  )

  const parentSchema =
    !isNewSchema && effectiveSchema?.parent_id
      ? (schemas?.find((s) => s.id === effectiveSchema.parent_id) ?? null)
      : null
  const [parentRecordId, setParentRecordId] = useState('')
  // Only need to know whether *any* parent-schema records exist — the
  // picker itself searches on demand rather than listing every candidate.
  const { data: parentPage } = useRecords(
    parentSchema ? datasetName : '',
    parentSchema ? { schema: parentSchema.name, limit: 1 } : undefined,
  )
  const hasParentCandidates = (parentPage?.total ?? 0) > 0
  const needsParent = !!parentSchema

  // ── CSV column mapping ───────────────────────────────────────────────
  const [columnMap, setColumnMap] = useState<Record<string, string>>({})
  const [newColumnFields, setNewColumnFields] = useState<
    Record<string, NewFieldDraft>
  >({})

  // Re-run whenever the CSV changes (see handleCsvFileChange) or the target
  // schema's field set changes (see the schema <Select>'s onChange below) —
  // called explicitly at those two points rather than reactively, so a
  // column the user has already remapped by hand doesn't get silently
  // overwritten by an unrelated re-render.
  function applyColumnSuggestions(csv: ParsedCsv, fields: SchemaField[]) {
    const suggested = suggestFieldMapping(csv.columns, fields)
    const nextMap: Record<string, string> = {}
    const nextDrafts: Record<string, NewFieldDraft> = {}
    for (const col of csv.columns) {
      if (suggested[col]) {
        nextMap[col] = suggested[col]!
      } else {
        nextMap[col] = NEW_FIELD
        nextDrafts[col] = {
          label: displayLabel(slugify(col) || col, null),
          name: slugify(col),
          type: inferColumnType(csv.rows.map((r) => r[col] ?? '')),
        }
      }
    }
    setColumnMap(nextMap)
    setNewColumnFields(nextDrafts)
  }

  function resolvedColumnTarget(
    col: string,
  ): { fieldName: string; dtype: string } | null {
    const choice = columnMap[col]
    if (!choice || choice === SKIP_COLUMN) return null
    if (choice === NEW_FIELD) {
      const draft = newColumnFields[col]
      return draft && draft.name
        ? { fieldName: draft.name, dtype: draft.type }
        : null
    }
    const f = availableFields.find((f) => f.name === choice)
    return f ? { fieldName: f.name, dtype: f.type } : null
  }

  // ── Files mapping ────────────────────────────────────────────────────
  const [fileFieldChoice, setFileFieldChoice] = useState<string>('')
  const [newFileField, setNewFileField] = useState<NewFieldDraft>({
    name: 'file',
    label: 'File',
    type: 'file',
  })
  const [strategyChoice, setStrategyChoice] = useState<Strategy>('create')
  const [keyFieldName, setKeyFieldName] = useState('')
  const [pattern, setPattern] = useState('')
  const [extraExtractEnabled, setExtraExtractEnabled] = useState(false)
  const [extraFieldChoice, setExtraFieldChoice] = useState('')
  const [newExtraField, setNewExtraField] = useState<NewFieldDraft>({
    name: '',
    label: '',
    type: 'string',
  })
  const extraOutputType = (
    extraFieldChoice === NEW_FIELD
      ? newExtraField.type
      : (availableNonFileFields.find((f) => f.name === extraFieldChoice)
          ?.type ?? 'string')
  ) as ExtractOutputType

  const canMatch = !isNewSchema && !!parentSchema
  // Match mode only makes sense once a parent-scoped existing schema is
  // chosen — derived rather than synced back into state via an effect, so
  // switching schemas can't leave a stale, no-longer-selectable strategy.
  const strategy: Strategy = canMatch ? strategyChoice : 'create'

  const filenames = files.map((f) => f.name)

  const { data: existingChildPage } = useRecords(
    strategy === 'match' && effectiveSchema && parentRecordId
      ? datasetName
      : '',
    strategy === 'match' && effectiveSchema
      ? {
          schema: effectiveSchema.name,
          parent_record_id: parentRecordId || undefined,
          limit: 1000,
        }
      : undefined,
  )
  const existingChildren = existingChildPage?.items ?? []

  const fileFieldName =
    fileFieldChoice === NEW_FIELD ? newFileField.name : fileFieldChoice

  // ── Plans (dry run) ──────────────────────────────────────────────────
  // Recomputed on every render rather than memoized — cheap relative to a
  // form render, and it keeps the confirm-step counts and the actual run
  // reading from the exact same (always-current) logic.
  function computeCsvPlan(): CsvRowPlan[] {
    if (mode !== 'csv' || !parsedCsv) return []
    const requiredFieldNames = availableFields
      .filter((f) => f.required)
      .map((f) => f.name)
    const targets = parsedCsv.columns
      .map((col) => ({ col, target: resolvedColumnTarget(col) }))
      .filter((t) => t.target)
    return parsedCsv.rows.map((row, i) => {
      const data: Record<string, unknown> = {}
      let skip: string | null = null
      for (const { col, target } of targets) {
        if (!target) continue
        const { value, error } = coerceCsvValue(row[col] ?? '', target.dtype)
        if (error) {
          skip = error
          break
        }
        if (value !== undefined) data[target.fieldName] = value
      }
      if (!skip) {
        const missing = requiredFieldNames.find((f) => data[f] === undefined)
        if (missing) skip = `missing required "${missing}"`
      }
      return { index: i, data, skip }
    })
  }

  function computeFilesPlan(): FilePlan[] {
    if (mode !== 'files') return []
    return files.map((file) => {
      const data: Record<string, unknown> = {}
      let skip: string | null = null
      let matchedRecord: CivexRecord | null = null

      if (strategy === 'match') {
        const extraction = extractFromFilename(file.name, pattern, 'string', '')
        if (extraction.error || extraction.value === null) {
          skip = `${extraction.error ?? 'no match'}`
        } else {
          const normalized = normalizeNumericKey(String(extraction.value))
          const typedKey: unknown = /^-?\d+$/.test(normalized)
            ? Number(normalized)
            : normalized
          matchedRecord =
            existingChildren.find(
              (r) => String(r.data[keyFieldName] ?? '') === normalized,
            ) ?? null
          if (!matchedRecord) data[keyFieldName] = typedKey
        }
      } else if (extraExtractEnabled) {
        const extraction = extractFromFilename(
          file.name,
          pattern,
          extraOutputType,
          '',
        )
        if (extraction.error) {
          skip = extraction.error
        } else if (extraction.value !== null) {
          const target =
            extraFieldChoice === NEW_FIELD
              ? newExtraField.name
              : extraFieldChoice
          if (target) data[target] = extraction.value
        }
      }

      return { file, data, matchedRecord, skip }
    })
  }

  const csvPlan: CsvRowPlan[] = computeCsvPlan()
  const filesPlan: FilePlan[] = computeFilesPlan()

  const csvCreateCount = csvPlan.filter((p) => !p.skip).length
  const csvSkipCount = csvPlan.filter((p) => p.skip).length
  const filesCreateCount = filesPlan.filter(
    (p) => !p.skip && !p.matchedRecord,
  ).length
  const filesUpdateCount = filesPlan.filter(
    (p) => !p.skip && p.matchedRecord,
  ).length
  const filesSkipCount = filesPlan.filter((p) => p.skip).length

  // ── Automation ───────────────────────────────────────────────────────
  const [saveAsAutomation, setSaveAsAutomation] = useState(false)
  const [automationLabel, setAutomationLabel] = useState('')

  // ── Run ──────────────────────────────────────────────────────────────
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState(0)
  const [runErrorBanner, setRunErrorBanner] = useState<string | null>(null)
  const [result, setResult] = useState<ImportOutcome | null>(null)

  const total = mode === 'csv' ? csvPlan.length : filesPlan.length

  // ── Validation ───────────────────────────────────────────────────────
  const sourceValid =
    mode === 'files'
      ? files.length > 0
      : !!parsedCsv && parsedCsv.columns.length > 0 && parsedCsv.rows.length > 0

  const schemaValid = isNewSchema
    ? !newSchema.name && !newSchema.label
      ? false
      : !nameError(newSchema.name)
    : !!effectiveSchema

  const mapValid =
    schemaValid &&
    (!needsParent || !!parentRecordId) &&
    (mode === 'csv'
      ? parsedCsv!.columns.some((c) => resolvedColumnTarget(c) !== null)
      : !!fileFieldName &&
        !nameError(fileFieldName) &&
        (strategy !== 'match' || (!!keyFieldName && !!pattern)))

  const automationValid = !saveAsAutomation || !!automationLabel.trim()

  // ── Execution ────────────────────────────────────────────────────────
  async function runImport() {
    setRunning(true)
    setRunErrorBanner(null)
    setProgress(0)
    try {
      let schemaName = targetSchemaName
      let liveSchema = effectiveSchema

      if (isNewSchema) {
        liveSchema = await schemasApi.create({
          name: newSchema.name,
          label: newSchema.label || undefined,
        })
        schemaName = liveSchema.name
      }

      if (mode === 'csv' && parsedCsv) {
        for (const col of parsedCsv.columns) {
          if (columnMap[col] === NEW_FIELD) {
            const draft = newColumnFields[col]
            await schemasApi.addField(schemaName, {
              name: draft.name,
              label: draft.label || undefined,
              type: draft.type,
            })
          }
        }
      } else if (mode === 'files') {
        if (fileFieldChoice === NEW_FIELD) {
          await schemasApi.addField(schemaName, {
            name: newFileField.name,
            label: newFileField.label || undefined,
            type: 'file',
          })
        }
        if (extraExtractEnabled && extraFieldChoice === NEW_FIELD) {
          await schemasApi.addField(schemaName, {
            name: newExtraField.name,
            label: newExtraField.label || undefined,
            type: newExtraField.type,
          })
        }
      }

      const created: CivexRecord[] = []
      const updated: CivexRecord[] = []
      const skipped: { label: string; reason: string }[] = []

      if (mode === 'csv') {
        for (const rowPlan of csvPlan) {
          if (rowPlan.skip) {
            skipped.push({
              label: `Row ${rowPlan.index + 1}`,
              reason: rowPlan.skip,
            })
          } else {
            try {
              const rec = await recordsApi.create(datasetName, {
                schema_name: schemaName,
                data: rowPlan.data,
                parent_record_id: parentRecordId || undefined,
              })
              created.push(rec)
            } catch (e) {
              skipped.push({
                label: `Row ${rowPlan.index + 1}`,
                reason: errorMessage(e),
              })
            }
          }
          setProgress((p) => p + 1)
        }
      } else {
        for (const filePlan of filesPlan) {
          if (filePlan.skip) {
            skipped.push({ label: filePlan.file.name, reason: filePlan.skip })
            setProgress((p) => p + 1)
            continue
          }
          try {
            const ref = await filesApi.upload(filePlan.file)
            if (filePlan.matchedRecord) {
              const rec = await recordsApi.update(filePlan.matchedRecord.id, {
                data: { ...filePlan.matchedRecord.data, [fileFieldName]: ref },
              })
              updated.push(rec)
            } else {
              const rec = await recordsApi.create(datasetName, {
                schema_name: schemaName,
                data: { ...filePlan.data, [fileFieldName]: ref },
                parent_record_id: parentRecordId || undefined,
              })
              created.push(rec)
            }
          } catch (e) {
            skipped.push({ label: filePlan.file.name, reason: errorMessage(e) })
          }
          setProgress((p) => p + 1)
        }
      }

      let automationStem: string | undefined
      let automationError: string | undefined
      if (saveAsAutomation) {
        try {
          const stem = slugify(automationLabel)
          if (mode === 'files') {
            const yaml = buildFilesImportWorkflowYaml({
              name: automationLabel,
              strategy,
              schemaName,
              fileField: fileFieldName,
              datasetName,
              parentRecordId: parentRecordId || undefined,
              keyField: strategy === 'match' ? keyFieldName : undefined,
              pattern: strategy === 'match' ? pattern : undefined,
            })
            await workflowsApi.save(stem, yaml)
          } else {
            const importSchemaName = `${schemaName}_import`
            let importSchema
            try {
              importSchema = await schemasApi.get(importSchemaName)
            } catch {
              importSchema = await schemasApi.create({
                name: importSchemaName,
                label: `${displayLabel(schemaName, liveSchema?.label)} import`,
                description: `Attach a new CSV here to re-run "${automationLabel}".`,
              })
            }
            if (!importSchema.fields.some((f) => f.name === 'csv_file')) {
              await schemasApi.addField(importSchemaName, {
                name: 'csv_file',
                label: 'CSV file',
                type: 'file',
                required: true,
              })
            }
            const fieldMapping: Record<string, string> = {}
            for (const col of parsedCsv!.columns) {
              const target = resolvedColumnTarget(col)
              if (target) fieldMapping[col] = target.fieldName
            }
            const yaml = buildCsvImportWorkflowYaml({
              name: automationLabel,
              triggerSchemaName: importSchemaName,
              csvFieldName: 'csv_file',
              targetSchemaName: schemaName,
              datasetName,
              fieldMapping,
            })
            await workflowsApi.save(stem, yaml)
          }
          automationStem = stem
        } catch (e) {
          automationError = errorMessage(e)
        }
      }

      setResult({ created, updated, skipped, automationStem, automationError })
      setStep('done')
    } catch (e) {
      setRunErrorBanner(errorMessage(e))
    } finally {
      setRunning(false)
    }
  }

  // ── Render ───────────────────────────────────────────────────────────
  return (
    <div className="space-y-6 max-w-4xl">
      <ol className="flex items-center gap-2 text-xs text-fg-muted">
        {(['source', 'map', 'confirm', 'done'] as WizardStep[]).map((s, i) => (
          <li key={s} className="flex items-center gap-2">
            {i > 0 && <span aria-hidden="true">/</span>}
            <span
              className={
                s === step
                  ? 'text-fg font-semibold'
                  : i <
                      (
                        ['source', 'map', 'confirm', 'done'] as WizardStep[]
                      ).indexOf(step)
                    ? 'text-accent'
                    : ''
              }
            >
              {
                {
                  source: 'Source',
                  map: 'Map',
                  confirm: 'Confirm',
                  done: 'Done',
                }[s]
              }
            </span>
          </li>
        ))}
      </ol>

      {step === 'source' && (
        <div className="space-y-4">
          <div className="flex gap-3">
            <button
              onClick={() => setMode('files')}
              className={`flex-1 flex items-center gap-3 px-4 py-4 rounded-md border text-left transition-colors cursor-pointer ${
                mode === 'files'
                  ? 'border-accent bg-accent-subtle'
                  : 'border-border hover:border-accent'
              }`}
            >
              <Upload size={18} className="text-accent shrink-0" />
              <span>
                <span className="block text-sm font-medium text-fg">Files</span>
                <span className="block text-xs text-fg-muted">
                  A folder of scans, images, recordings…
                </span>
              </span>
            </button>
            <button
              onClick={() => setMode('csv')}
              className={`flex-1 flex items-center gap-3 px-4 py-4 rounded-md border text-left transition-colors cursor-pointer ${
                mode === 'csv'
                  ? 'border-accent bg-accent-subtle'
                  : 'border-border hover:border-accent'
              }`}
            >
              <Database size={18} className="text-accent shrink-0" />
              <span>
                <span className="block text-sm font-medium text-fg">
                  Spreadsheet
                </span>
                <span className="block text-xs text-fg-muted">
                  A CSV of rows to turn into records
                </span>
              </span>
            </button>
          </div>

          {mode === 'files' && (
            <div className="space-y-2">
              <input
                id="import-files-input"
                type="file"
                multiple
                className="block w-full text-sm text-fg file:mr-3 file:py-2 file:px-3 file:rounded-md file:border-0 file:text-xs file:bg-canvas-subtle file:text-fg hover:file:bg-border-muted cursor-pointer"
                onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
              />
              {files.length > 0 && (
                <div className="border border-border rounded-md p-3 space-y-1">
                  <p className="text-xs font-medium text-fg">
                    {files.length} file{files.length === 1 ? '' : 's'} selected
                  </p>
                  <div className="max-h-40 overflow-y-auto text-xs font-mono text-fg-muted space-y-0.5">
                    {files.slice(0, 30).map((f, i) => (
                      <p key={i} className="truncate">
                        {f.name}
                      </p>
                    ))}
                    {files.length > 30 && <p>… and {files.length - 30} more</p>}
                  </div>
                </div>
              )}
            </div>
          )}

          {mode === 'csv' && (
            <div className="space-y-2">
              <input
                type="file"
                accept=".csv,text/csv"
                className="block w-full text-sm text-fg file:mr-3 file:py-2 file:px-3 file:rounded-md file:border-0 file:text-xs file:bg-canvas-subtle file:text-fg hover:file:bg-border-muted cursor-pointer"
                onChange={(e) =>
                  handleCsvFileChange(e.target.files?.[0] ?? null)
                }
              />
              {csvReadError && <FormError message={csvReadError} />}
              {parsedCsv && parsedCsv.columns.length > 0 && (
                <div className="border border-border rounded-md overflow-hidden">
                  <div className="px-3 py-2 text-xs font-medium text-fg bg-canvas-subtle border-b border-border">
                    {parsedCsv.columns.length} column
                    {parsedCsv.columns.length === 1 ? '' : 's'} ·{' '}
                    {parsedCsv.rows.length} row
                    {parsedCsv.rows.length === 1 ? '' : 's'}
                  </div>
                  <div className="overflow-x-auto max-h-64">
                    <table className="text-xs w-full">
                      <thead>
                        <tr>
                          {parsedCsv.columns.map((c) => (
                            <th
                              key={c}
                              className="text-left px-2 py-1.5 font-medium text-fg-muted whitespace-nowrap border-b border-border"
                            >
                              {c}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {parsedCsv.rows.slice(0, 5).map((row, i) => (
                          <tr key={i} className="border-t border-border-muted">
                            {parsedCsv!.columns.map((c) => (
                              <td
                                key={c}
                                className="px-2 py-1.5 text-fg whitespace-nowrap"
                              >
                                {row[c]}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
              {parsedCsv && parsedCsv.rows.length === 0 && (
                <FormError message="No data rows found in this file." />
              )}
            </div>
          )}

          <div className="flex justify-end">
            <Button
              variant="primary"
              disabled={!mode || !sourceValid}
              onClick={() => setStep('map')}
            >
              Continue <ArrowRight size={14} />
            </Button>
          </div>
        </div>
      )}

      {step === 'map' && mode && (
        <div className="space-y-5">
          <div className="space-y-2">
            <span className="text-xs font-semibold text-fg-muted uppercase tracking-wide">
              Record type
            </span>
            <Select
              value={schemaChoice}
              onChange={(e) => {
                const id = e.target.value
                setSchemaChoice(id)
                setParentRecordId('')
                if (parsedCsv) {
                  const fields =
                    id && id !== NEW_SCHEMA
                      ? (schemas?.find((s) => s.id === id)?.fields ?? [])
                      : []
                  applyColumnSuggestions(parsedCsv, fields)
                }
              }}
              className="w-full max-w-sm"
            >
              <option value="">— Select a record type —</option>
              <option value={NEW_SCHEMA}>+ Create a new record type</option>
              {schemas?.map((s) => (
                <option key={s.id} value={s.id}>
                  {displayLabel(s.name, s.label)}
                  {s.parent_id ? ' (child record)' : ''}
                </option>
              ))}
            </Select>
            {isNewSchema && (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 pt-2">
                <NameLabelFields
                  kind="Schema"
                  value={newSchema}
                  onChange={setNewSchema}
                  autoFocus
                />
              </div>
            )}
          </div>

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
                  No {displayLabel(parentSchema.name, parentSchema.label)}{' '}
                  records in this collection yet — add one first.
                </p>
              ) : (
                <RecordSearchPicker
                  schemaName={parentSchema.name}
                  value={parentRecordId || undefined}
                  onChange={(id) => setParentRecordId(id ?? '')}
                  placeholder="Search records…"
                  className="w-full max-w-sm"
                />
              )}
            </div>
          )}

          {mode === 'csv' && parsedCsv && (
            <div className="space-y-1">
              <span className="text-xs font-semibold text-fg-muted uppercase tracking-wide">
                Column mapping
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
                      <ArrowRight
                        size={12}
                        className="text-fg-subtle shrink-0"
                      />
                      <Select
                        size="sm"
                        value={columnMap[col] ?? SKIP_COLUMN}
                        onChange={(e) =>
                          setColumnMap((prev) => ({
                            ...prev,
                            [col]: e.target.value,
                          }))
                        }
                        className="w-56 shrink-0"
                      >
                        <option value={SKIP_COLUMN}>
                          — Skip this column —
                        </option>
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
                    {columnMap[col] === NEW_FIELD && newColumnFields[col] && (
                      <NewFieldEditor
                        draft={newColumnFields[col]}
                        onChange={(next) =>
                          setNewColumnFields((prev) => ({
                            ...prev,
                            [col]: next,
                          }))
                        }
                        typeOptions={SCALAR_TYPES}
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
                  value={fileFieldChoice}
                  onChange={(e) => setFileFieldChoice(e.target.value)}
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
                {fileFieldChoice === NEW_FIELD && (
                  <NewFieldEditor
                    draft={newFileField}
                    onChange={setNewFileField}
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
                      checked={strategyChoice === 'create'}
                      onChange={() => setStrategyChoice('create')}
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
                      checked={strategyChoice === 'match'}
                      onChange={() => setStrategyChoice('match')}
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
                      value={keyFieldName}
                      onChange={(e) => setKeyFieldName(e.target.value)}
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
                    pattern={pattern}
                    onPatternChange={setPattern}
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
                      checked={extraExtractEnabled}
                      onChange={(e) => setExtraExtractEnabled(e.target.checked)}
                    />
                    Also fill a field from the filename
                  </label>
                  {extraExtractEnabled && (
                    <div className="space-y-2 pl-3 border-l-2 border-accent-muted">
                      <Field label="Target field" span={6}>
                        <Select
                          size="sm"
                          value={extraFieldChoice}
                          onChange={(e) => setExtraFieldChoice(e.target.value)}
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
                      {extraFieldChoice === NEW_FIELD && (
                        <NewFieldEditor
                          draft={newExtraField}
                          onChange={setNewExtraField}
                          typeOptions={SCALAR_TYPES}
                        />
                      )}
                      <FilenamePatternPreview
                        filenames={filenames}
                        pattern={pattern}
                        onPatternChange={setPattern}
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
            <Button onClick={() => setStep('source')}>
              <ArrowLeft size={14} /> Back
            </Button>
            <Button
              variant="primary"
              disabled={!mapValid}
              onClick={() => setStep('confirm')}
            >
              Continue <ArrowRight size={14} />
            </Button>
          </div>
        </div>
      )}

      {step === 'confirm' && (
        <div className="space-y-5">
          <div className="border border-border rounded-md p-4 bg-canvas-subtle space-y-2">
            <p className="text-sm text-fg">
              {isNewSchema && (
                <>
                  Creates a new record type{' '}
                  <Badge variant="accent">
                    {newSchema.name || '(unnamed)'}
                  </Badge>
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
                      {filesSkipCount} file{filesSkipCount === 1 ? '' : 's'}{' '}
                      will be skipped.
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
                checked={saveAsAutomation}
                onChange={(e) => setSaveAsAutomation(e.target.checked)}
              />
              Save this as a reusable automation
            </label>
            {saveAsAutomation && (
              <div className="pl-3 border-l-2 border-accent-muted space-y-2">
                <Field
                  label="Automation name"
                  span={6}
                  hint={
                    mode === 'csv'
                      ? `Creates a "${targetSchemaName || 'record'}_import" record type — attach a new CSV to it to repeat this import.`
                      : 'Re-run it later from the Workflows page with a new folder of files.'
                  }
                >
                  <Input
                    size="sm"
                    value={automationLabel}
                    onChange={(e) => setAutomationLabel(e.target.value)}
                    placeholder={`Import ${targetSchemaName || 'records'}`}
                  />
                </Field>
              </div>
            )}
          </div>

          {runErrorBanner && <FormError message={runErrorBanner} />}

          <div className="flex justify-between items-center">
            <Button onClick={() => setStep('map')} disabled={running}>
              <ArrowLeft size={14} /> Back
            </Button>
            <Button
              variant="primary"
              disabled={!automationValid || running || total === 0}
              onClick={runImport}
            >
              {running ? (
                <>
                  <Spinner /> Importing {progress}/{total}…
                </>
              ) : (
                <>
                  <Check size={14} /> Import {total} record
                  {total === 1 ? '' : 's'}
                </>
              )}
            </Button>
          </div>
        </div>
      )}

      {step === 'done' && result && (
        <div className="space-y-5">
          <div className="border border-success-muted bg-success-subtle rounded-md p-4">
            <p className="text-sm text-success font-medium">
              {result.created.length} created
              {result.updated.length > 0 &&
                `, ${result.updated.length} updated`}
              {result.skipped.length > 0 &&
                `, ${result.skipped.length} skipped`}
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
                      variant={
                        result.created.includes(r) ? 'success' : 'default'
                      }
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
            <Link to={`/collections`}>
              <Button variant="primary">Done</Button>
            </Link>
            <Button
              onClick={() => {
                setStep('source')
                setMode(null)
                setFiles([])
                setParsedCsv(null)
                setSchemaChoice('')
                setColumnMap({})
                setNewColumnFields({})
                setFileFieldChoice('')
                setStrategyChoice('create')
                setKeyFieldName('')
                setPattern('')
                setExtraExtractEnabled(false)
                setParentRecordId('')
                setSaveAsAutomation(false)
                setAutomationLabel('')
                setResult(null)
              }}
            >
              Import more
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
