import { useState } from 'react'
import { useSchemas } from '../../hooks/useSchemas'
import { useCollections } from '../../hooks/useCollections'
import { useRecords, useHasSchemaRecords } from '../../hooks/useRecords'
import { schemasApi, type Schema } from '../../api/schemas'
import { auditApi } from '../../api/audit'
import { recordsApi, type CivexRecord } from '../../api/records'
import { collectionsApi } from '../../api/collections'
import { fileBatches, filesApi, type FileRef } from '../../api/files'
import { workflowsApi } from '../../api/workflows'
import { Stepper } from '../ui'
import { parseCsv, type ParsedCsv } from '../../utils/csv'
import { inferColumnType, suggestFieldMapping } from '../../utils/importMapping'
import { normalizeNumericKey } from '../../utils/filenamePattern'
import { extractFromFilename } from './FilenamePatternPreview'
import {
  buildCsvImportWorkflowYaml,
  buildFilesImportWorkflowYaml,
} from '../../utils/workflowYaml'
import { displayLabel, slugify, nameError } from '../../utils/naming'
import { errorMessage } from '../../lib/errors'
import { SourceStep } from './SourceStep'
import { MapStep } from './MapStep'
import { ConfirmStep } from './ConfirmStep'
import { DoneStep } from './DoneStep'
import {
  NEW_SCHEMA,
  NEW_COLLECTION,
  NEW_FIELD,
  initialMapState,
  initialConfirmState,
  coerceCsvValue,
  type Mode,
  type WizardStep,
  type Strategy,
  type CsvRowPlan,
  type FilePlan,
  type ImportOutcome,
} from './importWizardTypes'

export interface ImportWizardProps {
  /** Pre-chosen collection (e.g. entering from a collection page). Omit to
   * ask for one mid-wizard — see `schemaId` for the symmetric case. */
  datasetName?: string
  /** Pre-chosen schema (e.g. entering from a schema page) — skips the
   * "record type" picker entirely rather than just hiding it. */
  schemaId?: string
}

const STEPS: WizardStep[] = ['source', 'map', 'confirm', 'done']

export default function ImportWizard({
  datasetName,
  schemaId,
}: ImportWizardProps) {
  const [step, setStep] = useState<WizardStep>('source')
  const [mode, setMode] = useState<Mode | null>(null)

  // ── Source ────────────────────────────────────────────────────────────
  const [files, setFiles] = useState<File[]>([])
  const [csvReadError, setCsvReadError] = useState<string | null>(null)
  const [parsedCsv, setParsedCsv] = useState<ParsedCsv | null>(null)

  // ── Schema ────────────────────────────────────────────────────────────
  const { data: schemas } = useSchemas()
  const [mapState, setMapState] = useState(initialMapState)
  function patchMap(patch: Partial<typeof mapState>) {
    setMapState((prev) => ({ ...prev, ...patch }))
  }

  const presetSchema = schemaId
    ? (schemas?.find((s) => s.id === schemaId) ?? null)
    : null
  // schemaId was given but the schemas list hasn't loaded yet -- avoid a
  // one-frame flash of the "pick a record type" UI before snapping to
  // "already have one".
  const schemaResolving = !!schemaId && !schemas

  const isNewSchema = !presetSchema && mapState.schemaChoice === NEW_SCHEMA
  const effectiveSchema: Schema | null =
    presetSchema ??
    (isNewSchema
      ? null
      : (schemas?.find((s) => s.id === mapState.schemaChoice) ?? null))
  const targetSchemaName = isNewSchema
    ? mapState.newSchema.name
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
  const hasParentCandidates = useHasSchemaRecords(parentSchema?.name)
  const needsParent = !!parentSchema

  // ── Collection ───────────────────────────────────────────────────────
  const { data: collections } = useCollections()
  const showCollectionPicker = !datasetName

  // ── CSV column mapping ───────────────────────────────────────────────
  // Re-run whenever the CSV changes or the target schema's field set
  // changes -- called explicitly at those two points rather than
  // reactively, so a column the user has already remapped by hand doesn't
  // get silently overwritten by an unrelated re-render.
  function applyColumnSuggestions(csv: ParsedCsv, fields: Schema['fields']) {
    const suggested = suggestFieldMapping(csv.columns, fields)
    const nextMap: Record<string, string> = {}
    const nextDrafts: typeof mapState.newColumnFields = {}
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
    patchMap({ columnMap: nextMap, newColumnFields: nextDrafts })
  }

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

  function handleSchemaChoiceChange(id: string) {
    const patch: Partial<typeof mapState> = {
      schemaChoice: id,
      parentRecordId: '',
    }
    patchMap(patch)
    if (parsedCsv) {
      const fields =
        id && id !== NEW_SCHEMA
          ? (schemas?.find((s) => s.id === id)?.fields ?? [])
          : []
      applyColumnSuggestions(parsedCsv, fields)
    }
  }

  function resolvedColumnTarget(col: string): {
    fieldName: string
    dtype: string
    fieldUnit?: string
    columnUnit?: string
  } | null {
    const choice = mapState.columnMap[col]
    if (!choice || choice === '__skip__') return null
    if (choice === NEW_FIELD) {
      const draft = mapState.newColumnFields[col]
      return draft && draft.name
        ? { fieldName: draft.name, dtype: draft.type }
        : null
    }
    const f = availableFields.find((f) => f.name === choice)
    if (!f) return null
    const fieldUnit =
      f.type === 'float' && typeof f.restrictions?.unit === 'string'
        ? f.restrictions.unit
        : undefined
    return {
      fieldName: f.name,
      dtype: f.type,
      fieldUnit,
      columnUnit: fieldUnit ? mapState.columnUnits[col] : undefined,
    }
  }

  // ── Files mapping ────────────────────────────────────────────────────
  const extraOutputType = (
    mapState.extraFieldChoice === NEW_FIELD
      ? mapState.newExtraField.type
      : (availableNonFileFields.find(
          (f) => f.name === mapState.extraFieldChoice,
        )?.type ?? 'string')
  ) as 'string' | 'integer' | 'float' | 'date' | 'datetime'

  const canMatch = !isNewSchema && !!parentSchema
  // Match mode only makes sense once a parent-scoped existing schema is
  // chosen -- derived rather than synced back into state via an effect, so
  // switching schemas can't leave a stale, no-longer-selectable strategy.
  const strategy: Strategy = canMatch ? mapState.strategyChoice : 'create'

  const filenames = files.map((f) => f.name)

  // ── Confirm / collection choice ─────────────────────────────────────
  const [confirmState, setConfirmState] = useState(initialConfirmState)
  function patchConfirm(patch: Partial<typeof confirmState>) {
    setConfirmState((prev) => ({ ...prev, ...patch }))
  }
  const collectionIsNew = confirmState.collectionChoice === NEW_COLLECTION
  // The collection to scope reads against right now -- the prop if given,
  // else whatever's been chosen so far (empty until then; a brand-new
  // collection has no existing records to match against anyway, so leaving
  // this empty in that case is correct, not just a placeholder).
  const scopedDatasetName =
    datasetName ?? (collectionIsNew ? '' : confirmState.collectionChoice)

  const { data: existingChildPage } = useRecords(
    strategy === 'match' && effectiveSchema && mapState.parentRecordId
      ? scopedDatasetName
      : '',
    strategy === 'match' && effectiveSchema
      ? {
          schema: effectiveSchema.name,
          parent_record_id: mapState.parentRecordId || undefined,
          limit: 1000,
        }
      : undefined,
  )
  const existingChildren = existingChildPage?.items ?? []

  const fileFieldName =
    mapState.fileFieldChoice === NEW_FIELD
      ? mapState.newFileField.name
      : mapState.fileFieldChoice

  // ── Plans (dry run) ──────────────────────────────────────────────────
  // Recomputed on every render rather than memoized -- cheap relative to a
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
        const { value, error } = coerceCsvValue(row[col] ?? '', target.dtype, {
          fieldUnit: target.fieldUnit,
          columnUnit: target.columnUnit,
        })
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
        const extraction = extractFromFilename(
          file.name,
          mapState.pattern,
          'string',
          '',
        )
        if (extraction.error || extraction.value === null) {
          skip = `${extraction.error ?? 'no match'}`
        } else {
          const normalized = normalizeNumericKey(String(extraction.value))
          const typedKey: unknown = /^-?\d+$/.test(normalized)
            ? Number(normalized)
            : normalized
          matchedRecord =
            existingChildren.find(
              (r) => String(r.data[mapState.keyFieldName] ?? '') === normalized,
            ) ?? null
          if (!matchedRecord) data[mapState.keyFieldName] = typedKey
        }
      } else if (mapState.extraExtractEnabled) {
        const extraction = extractFromFilename(
          file.name,
          mapState.pattern,
          extraOutputType,
          '',
        )
        if (extraction.error) {
          skip = extraction.error
        } else if (extraction.value !== null) {
          const target =
            mapState.extraFieldChoice === NEW_FIELD
              ? mapState.newExtraField.name
              : mapState.extraFieldChoice
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

  // ── Run ──────────────────────────────────────────────────────────────
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState(0)
  const [runErrorBanner, setRunErrorBanner] = useState<string | null>(null)
  const [result, setResult] = useState<ImportOutcome | null>(null)
  // The collection actually used for the run just completed -- captured
  // separately from confirmState so "Done" can deep-link to it even though
  // confirmState.collectionChoice may still hold the NEW_COLLECTION
  // sentinel rather than the real name.
  const [ranDatasetName, setRanDatasetName] = useState('')

  const total = mode === 'csv' ? csvPlan.length : filesPlan.length

  // ── Validation ───────────────────────────────────────────────────────
  const sourceValid =
    mode === 'files'
      ? files.length > 0
      : !!parsedCsv && parsedCsv.columns.length > 0 && parsedCsv.rows.length > 0

  const schemaValid = presetSchema
    ? true
    : isNewSchema
      ? !(!mapState.newSchema.name && !mapState.newSchema.label) &&
        !nameError(mapState.newSchema.name)
      : !!effectiveSchema

  const mapValid =
    schemaValid &&
    (!needsParent || !!mapState.parentRecordId) &&
    (mode === 'csv'
      ? parsedCsv!.columns.some((c) => resolvedColumnTarget(c) !== null)
      : !!fileFieldName &&
        !nameError(fileFieldName) &&
        (strategy !== 'match' ||
          (!!mapState.keyFieldName && !!mapState.pattern)))

  // ── Execution ────────────────────────────────────────────────────────
  async function runImport() {
    setRunning(true)
    setRunErrorBanner(null)
    setProgress(0)
    try {
      let finalDatasetName = datasetName ?? confirmState.collectionChoice
      // The collection files are uploaded for (its home volume, if it has
      // one, receives new content).
      let finalCollectionId = collections?.find(
        (c) => c.name === finalDatasetName,
      )?.id
      if (!datasetName && collectionIsNew) {
        const created = await collectionsApi.create({
          name: confirmState.newCollection.name,
          description: confirmState.newCollection.description || undefined,
        })
        finalDatasetName = created.name
        finalCollectionId = created.id
      }
      setRanDatasetName(finalDatasetName)

      let schemaName = targetSchemaName
      let liveSchema = effectiveSchema

      if (isNewSchema) {
        liveSchema = await schemasApi.create({
          name: mapState.newSchema.name,
          label: mapState.newSchema.label || undefined,
        })
        schemaName = liveSchema.name
      }

      if (mode === 'csv' && parsedCsv) {
        for (const col of parsedCsv.columns) {
          if (mapState.columnMap[col] === NEW_FIELD) {
            const draft = mapState.newColumnFields[col]
            await schemasApi.addField(schemaName, {
              name: draft.name,
              label: draft.label || undefined,
              type: draft.type,
            })
          }
        }
      } else if (mode === 'files') {
        if (mapState.fileFieldChoice === NEW_FIELD) {
          await schemasApi.addField(schemaName, {
            name: mapState.newFileField.name,
            label: mapState.newFileField.label || undefined,
            type: 'file',
          })
        }
        if (
          mapState.extraExtractEnabled &&
          mapState.extraFieldChoice === NEW_FIELD
        ) {
          await schemasApi.addField(schemaName, {
            name: mapState.newExtraField.name,
            label: mapState.newExtraField.label || undefined,
            type: mapState.newExtraField.type,
          })
        }
      }

      // Everything this import writes is one event in history, not a line per
      // record. Best effort: without it the records are just logged singly.
      const batch = await auditApi
        .openBatch(files.length === 1 ? files[0].name : `${files.length} files`)
        .catch(() => null)
      const batchOptions = batch ? { batchId: batch.id } : undefined

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
              const rec = await recordsApi.create(
                finalDatasetName,
                {
                  schema_name: schemaName,
                  data: rowPlan.data,
                  parent_record_id: mapState.parentRecordId || undefined,
                },
                batchOptions,
              )
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
          }
        }
        // The files go in a few requests however many there are
        // (`fileBatches`), then each becomes or updates its record.
        const toAdd = filesPlan.filter((f) => !f.skip)
        for (const batch of fileBatches(
          toAdd,
          undefined,
          undefined,
          (f) => f.file.size,
        )) {
          let refs: (FileRef | undefined)[] = []
          let failure = ''
          try {
            const result = await filesApi.uploadBatch(
              batch.map((f) => f.file),
              undefined,
              finalCollectionId,
            )
            refs = result.files
            failure = result.stopped?.message ?? ''
          } catch (e) {
            failure = errorMessage(e)
          }
          for (const [i, filePlan] of batch.entries()) {
            const ref = refs[i]
            if (!ref) {
              skipped.push({
                label: filePlan.file.name,
                reason: failure || "The file couldn't be added",
              })
              setProgress((p) => p + 1)
              continue
            }
            await placeFile(filePlan, ref)
            setProgress((p) => p + 1)
          }
        }
      }

      async function placeFile(
        filePlan: (typeof filesPlan)[number],
        ref: FileRef,
      ) {
        try {
          if (filePlan.matchedRecord) {
            const rec = await recordsApi.update(
              filePlan.matchedRecord.id,
              {
                data: {
                  ...filePlan.matchedRecord.data,
                  [fileFieldName]: ref,
                },
              },
              batchOptions,
            )
            updated.push(rec)
          } else {
            const rec = await recordsApi.create(
              finalDatasetName,
              {
                schema_name: schemaName,
                data: { ...filePlan.data, [fileFieldName]: ref },
                parent_record_id: mapState.parentRecordId || undefined,
              },
              batchOptions,
            )
            created.push(rec)
          }
        } catch (e) {
          skipped.push({ label: filePlan.file.name, reason: errorMessage(e) })
        }
      }

      let automationStem: string | undefined
      let automationError: string | undefined
      if (confirmState.saveAsAutomation) {
        try {
          const stem = slugify(confirmState.automationLabel)
          if (mode === 'files') {
            const yaml = buildFilesImportWorkflowYaml({
              name: confirmState.automationLabel,
              strategy,
              schemaName,
              fileField: fileFieldName,
              datasetName: finalDatasetName,
              parentRecordId: mapState.parentRecordId || undefined,
              keyField:
                strategy === 'match' ? mapState.keyFieldName : undefined,
              pattern: strategy === 'match' ? mapState.pattern : undefined,
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
                description: `Attach a new CSV here to re-run "${confirmState.automationLabel}".`,
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
              name: confirmState.automationLabel,
              triggerSchemaName: importSchemaName,
              csvFieldName: 'csv_file',
              targetSchemaName: schemaName,
              datasetName: finalDatasetName,
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

  function importMore() {
    setStep('source')
    setMode(null)
    setFiles([])
    setParsedCsv(null)
    setMapState(initialMapState())
    setConfirmState(initialConfirmState())
    setResult(null)
  }

  const doneHref = schemaId
    ? `/schemas/${schemaId}`
    : `/collections/${encodeURIComponent(ranDatasetName || datasetName || '')}`

  // ── Render ───────────────────────────────────────────────────────────
  if (schemaResolving) return null

  return (
    <div className="space-y-6 max-w-4xl">
      <Stepper
        steps={[
          { label: 'Source' },
          { label: 'Map' },
          { label: 'Confirm' },
          { label: 'Done' },
        ]}
        activeIndex={STEPS.indexOf(step)}
      />

      {step === 'source' && (
        <SourceStep
          mode={mode}
          onModeChange={setMode}
          files={files}
          onFilesChange={setFiles}
          csvReadError={csvReadError}
          parsedCsv={parsedCsv}
          onCsvFileChange={handleCsvFileChange}
          sourceValid={sourceValid}
          onContinue={() => setStep('map')}
        />
      )}

      {step === 'map' && mode && (
        <MapStep
          mode={mode}
          state={mapState}
          onChange={patchMap}
          showSchemaPicker={!presetSchema}
          schemas={schemas}
          isNewSchema={isNewSchema}
          onSchemaChoiceChange={handleSchemaChoiceChange}
          availableFields={availableFields}
          availableFileFields={availableFileFields}
          availableNonFileFields={availableNonFileFields}
          targetSchemaName={targetSchemaName}
          needsParent={needsParent}
          parentSchema={parentSchema}
          hasParentCandidates={hasParentCandidates}
          parsedCsv={parsedCsv}
          collectionTimeZone={
            datasetName
              ? (collections?.find((c) => c.name === datasetName)?.timezone ??
                null)
              : undefined
          }
          canMatch={canMatch}
          strategy={strategy}
          filenames={filenames}
          extraOutputType={extraOutputType}
          mapValid={mapValid}
          onBack={() => setStep('source')}
          onContinue={() => setStep('confirm')}
        />
      )}

      {step === 'confirm' && (
        <ConfirmStep
          mode={mode!}
          isNewSchema={isNewSchema}
          newSchemaName={mapState.newSchema.name}
          targetSchemaName={targetSchemaName}
          csvCreateCount={csvCreateCount}
          csvSkipCount={csvSkipCount}
          filesCreateCount={filesCreateCount}
          filesUpdateCount={filesUpdateCount}
          filesSkipCount={filesSkipCount}
          csvPlan={csvPlan}
          filesPlan={filesPlan}
          showCollectionPicker={showCollectionPicker}
          collections={collections}
          state={confirmState}
          onChange={patchConfirm}
          runErrorBanner={runErrorBanner}
          running={running}
          progress={progress}
          total={total}
          onBack={() => setStep('map')}
          onRun={runImport}
        />
      )}

      {step === 'done' && result && (
        <DoneStep
          result={result}
          doneHref={doneHref}
          onImportMore={importMore}
        />
      )}
    </div>
  )
}
