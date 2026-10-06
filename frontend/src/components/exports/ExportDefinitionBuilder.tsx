import { useState } from 'react'
import type { ExportDefinition } from '../../api/exportDefinitions'
import type { FileSelection } from '../../api/fileAccess'
import type { Schema } from '../../api/schemas'
import { useSaveExportDefinition } from '../../hooks/useExportDefinitions'
import { useExportPreview } from '../../hooks/useExportPreview'
import { errorMessage } from '../../lib/errors'
import {
  definitionBody,
  describeDefinition,
  draftFrom,
  emptyDraft,
  kindsIn,
  oneTimeSelection,
  previewSelection,
  type Draft,
} from '../../utils/exportBuilder'
import { schemaLevels } from '../../utils/hierarchy'
import { displayLabel } from '../../utils/naming'
import {
  copyToDrive,
  downloadZip,
  openAsFolder,
  type FlowContext,
} from '../files/fileFlows'
import { PROJECT } from '../../hooks/useDriveChoice'
import { Button, ErrorState, Input, Select, Spinner, Stepper } from '../ui'
import { FilePreviewList } from './FilePreviewList'
import { FilesStep, LayoutStep, Row } from './ExportSteps'
import { JustTheTable } from './JustTheTable'
import { levelsFor, pluralize } from '../../utils/exportLevels'
import { MethodStep, type Method } from './MethodStep'

type StepId = 'what' | 'layout' | 'finish'
const ALL_STEPS: { id: StepId; label: string }[] = [
  { id: 'what', label: 'What' },
  { id: 'layout', label: 'Layout' },
  { id: 'finish', label: 'Finish' },
]
/** The folder's layout only matters when there are files to arrange. */
const stepsFor = (files: boolean) =>
  files ? ALL_STEPS : ALL_STEPS.filter((s) => s.id !== 'layout')

/** A saved export of this kind can be offered in the Files menu: one click to the
 * builder, already filled in. */
export interface SavedPreset {
  label: string
  /** What it takes when run where the person is (the saved export, here). */
  selection: FileSelection
  folderName: string
  definition?: ExportDefinition
}

/** Build an export: which files, how the folder is laid out, then finish.
 *
 * One builder for two jobs, differing only in how it finishes:
 *  - **save** (`attach`): saves it with a schema, to be offered wherever that
 *    schema is. Finishing asks for a name.
 *  - **run** (`run`): gets the files now, from where the person clicked
 *    (a record, a collection, a list). Finishing asks how: a folder of links,
 *    copies on a drive, or a zip. A saved export opens it already filled in, at
 *    the last step, with the other steps a Back away.
 *
 * Both show what the folder would hold, against real data, before anything is
 * made. */
export function ExportBuilder({
  schemas,
  attach,
  run,
  scopeSchema,
  onDone,
}: {
  schemas: Schema[]
  attach?: { schema: Schema; editing?: ExportDefinition }
  run?: {
    context: FileSelection
    folderName: string
    preset?: SavedPreset
    ctx: FlowContext
  }
  /** The kind whose tree the choices come from; none means every kind. */
  scopeSchema?: string
  onDone: () => void
}) {
  const initial: Draft = attach?.editing
    ? draftFrom(attach.editing)
    : run?.preset?.definition
      ? draftFrom(run.preset.definition)
      : {
          ...emptyDraft,
          layout: run?.context.layout ?? emptyDraft.layout,
          // Where the export starts from a list, its table is what the list
          // shows (its columns), and a list with no files is a table alone.
          files: run?.context.files !== false,
          tables: run?.context.tables ?? [],
        }
  const [draft, setDraft] = useState<Draft>(initial)
  // An export from a list begins as just its table; the rest is one click away.
  const [simple, setSimple] = useState(
    !!run &&
      !run.preset &&
      run.context.files === false &&
      initial.tables.length === 1,
  )
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }))
  const steps = stepsFor(draft.files)
  const [step, setStep] = useState(
    run?.preset ? stepsFor(initial.files).length - 1 : 0,
  )
  const stepId = steps[Math.min(step, steps.length - 1)].id

  // Saving: the kind of record it starts from, which is the one choice that
  // decides what the rest can be (the folders below are that kind and what is
  // inside it) and where it is offered.
  const [attachedTo, setAttachedTo] = useState(
    attach?.editing?.schema_name ?? attach?.schema.name ?? '',
  )
  const save = useSaveExportDefinition(attachedTo)
  // Running: how to get the files.
  const [picked, setMethod] = useState<Method>(initial.files ? 'link' : 'zip')
  // With no files there is nothing to link to.
  const method: Method = !draft.files && picked === 'link' ? 'zip' : picked
  const [drive, setDrive] = useState<string | null>(null)

  const scope = attach
    ? attachedTo
    : (scopeSchema ?? run?.preset?.definition?.schema_name)
  const label = (name: string) =>
    displayLabel(name, schemas.find((s) => s.name === name)?.label)

  // What is exported: the saved export itself when it is unchanged, otherwise
  // the choices made here, limited to where the person clicked.
  const unchanged =
    !!run?.preset && JSON.stringify(draft) === JSON.stringify(initial)
  const scopeKinds = run?.preset?.definition
    ? kindsIn(schemas, run.preset.definition.schema_name).map((s) => s.name)
    : undefined
  const selection: FileSelection = run
    ? unchanged
      ? run.preset!.selection
      : oneTimeSelection(run.context, draft, scopeKinds)
    : previewSelection(draft, attachedTo, schemas)
  const lastStep = stepId === 'finish'
  // What it would make, worked out on the last step and kept up to date as the
  // choices change there.
  const preview = useExportPreview(selection, lastStep)

  function saveIt() {
    if (!attach) return
    const body = definitionBody(draft)
    save.mutate(
      attach.editing
        ? {
            name: attach.editing.name,
            body: {
              rename: body.name !== attach.editing.name ? body.name : undefined,
              holder: body.holder,
              fields: body.fields,
              filter_tree: body.filter_tree,
              files_layout: body.files_layout,
              include_files: body.include_files,
              tables: body.tables,
            },
          }
        : { body },
      { onSuccess: onDone },
    )
  }

  function runIt() {
    if (!run) return
    const name = unchanged ? run.preset!.folderName : run.folderName
    onDone()
    if (method === 'zip') return void downloadZip(run.ctx, selection, name)
    if (method === 'copy')
      return void copyToDrive(
        run.ctx,
        selection,
        name,
        !drive || drive === PROJECT ? undefined : drive,
      )
    void openAsFolder(run.ctx, selection, name)
  }

  // The kinds the export starts from and everything inside it, by name, for
  // saying where it is offered.
  const startsWithin = attach
    ? kindsIn(schemas, attachedTo).map((s) => label(s.name))
    : []
  const words = (names: string[]) =>
    names.length < 2
      ? (names[0] ?? '')
      : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`

  // Where a saved export will be offered: the schema it is saved with, down to
  // the kind that holds the files.
  const offeredOn = kindsIn(schemas, attachedTo)
    .filter(
      (s) =>
        !draft.holder ||
        kindsIn(schemas, s.name).some((k) => k.name === draft.holder),
    )
    .map((s) => label(s.name))

  // A filter tests one kind of record, which a list or ticked rows can't be given.
  const withFilter = !(run?.context.schema_name || run?.context.record_ids)
  const noColumns =
    draft.tables.some((t) => t.columns?.length === 0) ||
    (!draft.files && draft.tables.length === 0)
  const finishLabel = attach
    ? save.isPending
      ? 'Saving…'
      : attach.editing
        ? 'Save changes'
        : 'Save export'
    : method === 'zip'
      ? 'Download'
      : method === 'copy'
        ? 'Copy'
        : 'Open folder'

  return (
    <div className="space-y-8 p-2">
      <Stepper
        steps={steps}
        activeIndex={steps.findIndex((s) => s.id === stepId)}
      />

      <div className="min-h-56 space-y-7 py-2">
        {stepId === 'what' && (
          <>
            {attach && (
              <Row label="Starts from">
                {attach.editing ? (
                  <p className="text-base font-medium text-fg">
                    {label(attachedTo)}
                  </p>
                ) : (
                  <Select
                    value={attachedTo}
                    aria-label="Starts from"
                    size="lg"
                    className="w-full max-w-xl"
                    onChange={(e) => {
                      setAttachedTo(e.target.value)
                      // What was ticked belonged to the other tree of folders.
                      setDraft((d) => ({ ...emptyDraft, name: d.name }))
                    }}
                  >
                    {schemaLevels(schemas.filter((s) => !s.deleted_at)).map(
                      (l) => (
                        <option key={l.schema.name} value={l.schema.name}>
                          {'\u00A0\u00A0'.repeat(l.depth)}
                          {displayLabel(l.schema.name, l.schema.label)}
                        </option>
                      ),
                    )}
                  </Select>
                )}
                <p className="text-sm text-fg-muted">
                  It takes {label(attachedTo)}
                  {startsWithin.length > 1
                    ? ` and everything inside it, and is offered on every ${words(startsWithin)} page`
                    : `, and is offered on every ${label(attachedTo)} page`}{' '}
                  and on collections that use{' '}
                  {startsWithin.length > 1 ? 'them' : 'it'}.
                </p>
              </Row>
            )}
            {simple ? (
              <Row label="Export">
                <JustTheTable
                  draft={draft}
                  set={set}
                  placeholder={pluralize(label(run?.context.schema_name ?? ''))}
                  canAddFiles={levelsFor(
                    schemas,
                    run?.context.schema_name,
                  ).some((l) => l.fileFields.length > 0)}
                  onMore={() => setSimple(false)}
                />
              </Row>
            ) : (
              <FilesStep
                // A new tree of folders when the kind it starts from changes.
                key={attachedTo}
                schemas={schemas}
                scopeSchema={scope}
                draft={draft}
                set={set}
                withFilter={withFilter}
                fixedKind={run?.context.schema_name}
              />
            )}
          </>
        )}

        {stepId === 'layout' && <LayoutStep draft={draft} set={set} />}

        {lastStep && (
          <>
            {attach && (
              <Row label="Name">
                <Input
                  value={draft.name}
                  onChange={(e) => set({ name: e.target.value })}
                  placeholder="Contour files, flat"
                  aria-label="Name"
                  size="lg"
                  className="w-full max-w-xl"
                />
              </Row>
            )}

            <Row label="Summary">
              <dl className="grid max-w-xl grid-cols-[7rem_1fr] gap-y-1.5 text-sm">
                <dt className="text-fg-muted">Takes</dt>
                <dd className="text-fg">
                  {describeDefinition(
                    {
                      holder: draft.holder || null,
                      fields: draft.files ? draft.fields : [],
                      files_layout: draft.layout,
                      filter_tree: draft.holder ? draft.filter : null,
                      include_files: draft.files,
                      tables: draft.tables,
                    },
                    schemas,
                  )}
                </dd>
                {attach && (
                  <>
                    <dt className="text-fg-muted">Offered on</dt>
                    <dd className="text-fg">
                      {['Collections', ...offeredOn].join(' · ')}
                    </dd>
                  </>
                )}
              </dl>
            </Row>

            <Row label="What it makes">
              {preview.error != null ? (
                <ErrorState message={errorMessage(preview.error)} />
              ) : preview.data ? (
                <div
                  aria-busy={preview.isFetching}
                  className={preview.isFetching ? 'opacity-60' : ''}
                >
                  <FilePreviewList data={preview.data} />
                </div>
              ) : (
                <Spinner />
              )}
            </Row>

            {run && (
              <Row label={draft.files ? 'Get the files' : 'Get the tables'}>
                <MethodStep
                  files={draft.files}
                  method={method}
                  setMethod={setMethod}
                  drive={drive}
                  setDrive={setDrive}
                />
              </Row>
            )}

            {save.error != null && (
              <p role="alert" className="text-sm text-danger">
                {errorMessage(save.error)}
              </p>
            )}
          </>
        )}
      </div>

      <div className="flex items-center justify-between border-t border-border pt-6">
        <Button
          size="lg"
          variant="ghost"
          onClick={() =>
            setStep(Math.max(0, steps.findIndex((s) => s.id === stepId) - 1))
          }
          disabled={stepId === 'what'}
        >
          Back
        </Button>
        {!lastStep ? (
          <Button
            size="lg"
            variant="primary"
            disabled={noColumns}
            onClick={() => setStep(steps.findIndex((s) => s.id === stepId) + 1)}
          >
            Next:{' '}
            {steps[
              steps.findIndex((s) => s.id === stepId) + 1
            ].label.toLowerCase()}
          </Button>
        ) : (
          <Button
            size="lg"
            variant="primary"
            onClick={attach ? saveIt : runIt}
            disabled={
              noColumns ||
              (attach ? !draft.name.trim() || save.isPending : false)
            }
          >
            {finishLabel}
          </Button>
        )}
      </div>
    </div>
  )
}
