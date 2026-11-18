import { useState, type ReactNode } from 'react'
import type { Field as SchemaField } from '../../api/schemas'
import type {
  TrialMany,
  TrialOnRecord,
  TrialRecordChange,
  TrialResult,
  WorkflowInput,
} from '../../api/workflows'
import type { PluginInfo } from '../../api/plugins'
import { ApiError } from '../../api/client'
import { useWorkflowPreview } from '../../hooks/useWorkflows'
import { useDebouncedValue } from '../../hooks/useDebouncedValue'
import { useSchemas } from '../../hooks/useSchemas'
import { displayLabel } from '../../utils/naming'
import {
  Badge,
  Button,
  Card,
  DataTable,
  Disclosure,
  Field,
  FileDropZone,
  type DataTableColumn,
} from '../ui'
import { MultiRecordSearchPicker } from '../records/RecordSearchPicker'
import { RecordLink } from '../records/RecordLink'
import { FieldValue } from '../records/FieldValue'
import {
  explainFailure,
  stepProblems,
  stepStory,
} from '../../utils/runNarrative'
import type { WorkflowValidationIssue } from '../../utils/workflowValidationErrors'

interface Props {
  /** The YAML to try: what is on screen, saved or not. */
  content: string
  /** The kind of record it runs on ('' while not chosen). */
  schema: string
  inputs: Record<string, WorkflowInput>
  plugins: PluginInfo[]
  /** Whether it is finished enough to try; `waiting` says what is missing. */
  ready?: boolean
  waiting?: string
  /** Called when the server refuses the YAML itself, with its problems
   * (they are listed here too). */
  onInvalid?: (issues: WorkflowValidationIssue[]) => void
  /** Shown under the outcome: e.g. a "Turn it on" button, given whether it
   * ran without failing on every record. */
  after?: (allOk: boolean) => ReactNode
}

function asField(f: { field: string; label: string; dtype: string | null }) {
  return {
    id: f.field,
    name: f.field,
    label: f.label,
    type: f.dtype ?? 'string',
    required: false,
    restrictions: {},
    default: null,
    position: null,
  } satisfies SchemaField
}

const ACTION_WORDS: Record<TrialRecordChange['action'], string> = {
  created: 'Would be added',
  updated: 'Would change',
  deleted: 'Would be deleted',
}

function ChangeCard({ change }: { change: TrialRecordChange }) {
  const columns: DataTableColumn<TrialRecordChange['fields'][number]>[] = [
    { key: 'label', header: 'Field', render: (f) => f.label },
  ]
  if (change.action !== 'created')
    columns.push({
      key: 'before',
      header: 'Now',
      render: (f) => <FieldValue value={f.before} field={asField(f)} />,
    })
  columns.push({
    key: 'after',
    header: change.action === 'created' ? 'Value' : 'After the run',
    render: (f) => <FieldValue value={f.after} field={asField(f)} />,
  })
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Badge
            variant={
              change.action === 'created'
                ? 'success'
                : change.action === 'deleted'
                  ? 'danger'
                  : 'accent'
            }
          >
            {ACTION_WORDS[change.action]}
          </Badge>
          {change.action === 'created' ? (
            <span>
              a new {change.schema_name}
              {change.name ? `: ${change.name}` : ''}
            </span>
          ) : (
            <span>
              {change.schema_name}{' '}
              <RecordLink id={change.record_id} fallback={change.name} />
            </span>
          )}
        </span>
      }
      flush={change.fields.length > 0}
    >
      {change.fields.length > 0 && (
        <DataTable
          dense
          columns={columns}
          rows={change.fields}
          getRowId={(f) => f.field}
        />
      )}
    </Card>
  )
}

function Outcome({
  result,
  plugins,
}: {
  result: TrialResult
  plugins: PluginInfo[]
}) {
  const problems = stepProblems(result.steps)
  const failure = result.error ? explainFailure(result.error) : null
  const failedStep = result.steps.find((s) => s.status === 'failed')
  const stepName = (id: string) => {
    const at = result.steps.findIndex((s) => s.step_id === id)
    const plugin = plugins.find((p) => p.id === result.steps[at]?.plugin)
    return `Step ${at + 1}${plugin ? `, ${plugin.name}` : ''}`
  }
  const created = result.changes.filter((c) => c.action === 'created').length
  const changed = result.changes.length - created
  const summary = [
    created > 0 && `add ${created} record${created === 1 ? '' : 's'}`,
    changed > 0 && `change ${changed} record${changed === 1 ? '' : 's'}`,
  ].filter(Boolean)

  return (
    <div className="space-y-3" role="status">
      {failure ? (
        <div className="rounded-md border border-danger-subtle-border bg-danger-subtle p-3 text-sm">
          <p className="font-medium text-danger">
            {failedStep ? `${stepName(failedStep.step_id)} failed: ` : ''}
            {result.error?.message}
          </p>
          <p className="mt-1 text-fg-muted">{failure.whatToDo}</p>
        </div>
      ) : (
        <p className="text-sm text-fg">
          {summary.length
            ? `It would ${summary.join(' and ')}.`
            : 'It would change nothing.'}
        </p>
      )}
      {problems.total > 0 && (
        <div className="rounded-md border border-attention-muted bg-attention-subtle p-3 text-sm">
          <p className="font-medium">{problems.lines.join('; ')}.</p>
          <ul className="mt-1 max-h-32 list-disc overflow-auto pl-5 text-xs">
            {problems.items.slice(0, 50).map((p, i) => (
              <li key={i}>{p.text}</li>
            ))}
          </ul>
        </div>
      )}
      {Object.entries(result.would_start).map(([wf, n]) => (
        <p key={wf} className="text-sm text-fg-muted">
          Its saves would also start “{wf}” on {n} record{n === 1 ? '' : 's'}.
        </p>
      ))}
      {result.changes.map((c) => (
        <ChangeCard key={c.record_id} change={c} />
      ))}
      {result.steps.length > 0 && (
        <Disclosure summary="Step by step">
          <ol className="space-y-1 p-3 text-xs">
            {result.steps.map((s) => (
              <li key={s.step_id}>
                <span className="font-medium">{stepName(s.step_id)}</span>:{' '}
                {s.status === 'failed' ? s.error : stepStory(s)}
              </li>
            ))}
          </ol>
        </Disclosure>
      )}
    </div>
  )
}

/** One record's outcome in a line: the fields it would set on the record
 * itself, then what else it would do, or where it fails. */
function Brief({
  trial,
  plugins,
}: {
  trial: TrialOnRecord
  plugins: PluginInfo[]
}) {
  const r = trial.result
  if (!r) return <span className="text-fg-muted">{trial.problem}</span>
  if (!r.ok) {
    const at = r.steps.findIndex((s) => s.status === 'failed')
    const plugin = plugins.find((p) => p.id === r.steps[at]?.plugin)
    return (
      <span className="text-danger">
        {at >= 0
          ? `Step ${at + 1}${plugin ? ` (${plugin.name})` : ''} fails: `
          : 'Fails: '}
        {r.error?.message}
      </span>
    )
  }
  const own = r.changes.find(
    (c) => c.record_id === trial.record_id && c.action === 'updated',
  )
  const rest = r.changes.filter((c) => c !== own)
  const count = (action: TrialRecordChange['action']) =>
    rest.filter((c) => c.action === action).length
  const more: string[] = []
  if (count('created'))
    more.push(
      `adds ${count('created')} record${count('created') === 1 ? '' : 's'}`,
    )
  if (count('updated'))
    more.push(
      `changes ${count('updated')} other record${count('updated') === 1 ? '' : 's'}`,
    )
  if (count('deleted')) more.push(`deletes ${count('deleted')}`)
  const problems = stepProblems(r.steps)
  if (!own && more.length === 0 && problems.total === 0)
    return <span className="text-fg-muted">Changes nothing</span>
  return (
    <span className="flex flex-wrap items-baseline gap-x-2">
      {own?.fields.slice(0, 2).map((f) => (
        <span key={f.field}>
          {f.label} → <FieldValue value={f.after} field={asField(f)} />
        </span>
      ))}
      {own && own.fields.length > 2 && (
        <span className="text-fg-muted">+{own.fields.length - 2} more</span>
      )}
      {more.length > 0 && <span>{more.join(', ')}</span>}
      {problems.total > 0 && (
        <span className="text-attention">{problems.lines.join('; ')}</span>
      )}
    </span>
  )
}

const signature = (t: TrialOnRecord) =>
  JSON.stringify(
    t.result
      ? { ok: t.result.ok, c: t.result.changes, e: t.result.error?.message }
      : t.problem,
  )

/** The records whose outcome differs from the answer before: what the last
 * edit did. */
function useChangedSince(data: TrialMany | undefined) {
  const [seen, setSeen] = useState<{
    data: TrialMany | undefined
    sigs: Map<string, string>
    changed: Set<string>
  }>({ data: undefined, sigs: new Map(), changed: new Set() })
  if (data && data !== seen.data) {
    const sigs = new Map(data.trials.map((t) => [t.record_id, signature(t)]))
    const changed = new Set(
      seen.data
        ? [...sigs]
            .filter(
              ([id, sig]) => seen.sigs.has(id) && seen.sigs.get(id) !== sig,
            )
            .map(([id]) => id)
        : [],
    )
    setSeen({ data, sigs, changed })
  }
  return seen.changed
}

/** What the workflow on screen would do, kept up to date as it is edited: it
 * is run on a few records and undone each time (the latest changed of its
 * kind, or the ones chosen), and each record's outcome is a line that opens
 * onto the detail. */
export function TrialPanel({
  content,
  schema,
  inputs,
  plugins,
  ready = true,
  waiting,
  onInvalid,
  after,
}: Props) {
  const [chosen, setChosen] = useState<string[] | null>(null)
  const [files, setFiles] = useState<Record<string, File[]>>({})
  const { data: schemas = [] } = useSchemas()
  const kind = schemas.find((s) => s.name === schema)
  const label = kind ? displayLabel(kind.name, kind.label) : schema
  const fileInputs = Object.entries(inputs).filter(
    ([, i]) => i.type === 'files',
  )
  const filesGiven = fileInputs.every(
    ([name]) => (files[name]?.length ?? 0) > 0,
  )
  // Typing in the builder asks once it pauses, not on every key.
  const asked = useDebouncedValue(content, 600)
  const ids = chosen ?? []
  // Only what is on screen is tried: `ready` describes it, not the YAML of a
  // moment ago that the pause is still holding.
  const enabled =
    !!schema &&
    ready &&
    asked === content &&
    filesGiven &&
    (chosen === null || chosen.length > 0)
  const preview = useWorkflowPreview(asked, ids, files, enabled)
  const changed = useChangedSince(preview.data)
  const invalid =
    preview.error instanceof ApiError && Array.isArray(preview.error.detail)
      ? (preview.error.detail as WorkflowValidationIssue[])
      : null
  const [reported, setReported] = useState<unknown>(null)
  if (invalid && preview.error !== reported) {
    setReported(preview.error)
    onInvalid?.(invalid)
  }
  const refused = preview.error && !invalid ? preview.error.message : null
  const shown = !!schema && ready && filesGiven
  const trials = shown && !preview.error ? (preview.data?.trials ?? []) : []
  const changing = trials.filter(
    (t) => t.result?.ok && t.result.changes.length > 0,
  ).length
  const failing = trials.filter((t) => t.result && !t.result.ok).length
  const busy = preview.isFetching || asked !== content

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          Preview
          {shown && busy && (
            <span className="text-xs font-normal text-fg-muted">Updating…</span>
          )}
        </span>
      }
      info="It runs on a few records each time you change it, then undoes everything, so you can see what it would do. A plugin of yours that reaches outside civex (a web request, a file of its own) still does that for real."
    >
      <div className="space-y-3">
        {!schema ? (
          <p className="text-sm text-fg-muted">
            Choose the kind of record it runs on to see what it would do.
          </p>
        ) : (
          <>
            {chosen === null ? (
              <p className="flex flex-wrap items-center gap-2 text-sm">
                <span>
                  On the{' '}
                  {preview.data && preview.data.trials.length < 5
                    ? preview.data.trials.length
                    : 5}{' '}
                  {label} records changed last.
                </span>
                <Button size="sm" variant="ghost" onClick={() => setChosen([])}>
                  Choose records…
                </Button>
              </p>
            ) : (
              <Field label={`On these ${label} records`}>
                <div className="space-y-1">
                  <MultiRecordSearchPicker
                    schemaName={schema}
                    value={chosen}
                    onChange={setChosen}
                    placeholder={`Search ${label} records`}
                  />
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setChosen(null)}
                  >
                    Use the latest instead
                  </Button>
                </div>
              </Field>
            )}
            {fileInputs.map(([name, decl]) => (
              <Field key={name} label={decl.label || 'Files'}>
                <FileDropZone
                  multiple
                  inputLabel={`${decl.label || name}: choose files`}
                  onFiles={(picked) =>
                    setFiles((prev) => ({ ...prev, [name]: picked }))
                  }
                >
                  {files[name]?.length
                    ? `${files[name].length} file${files[name].length === 1 ? '' : 's'} chosen`
                    : 'Choose some files to see what it makes of them'}
                </FileDropZone>
              </Field>
            ))}
            {!ready && waiting && (
              <p className="text-sm text-fg-muted">{waiting}</p>
            )}
          </>
        )}
        {refused && <p className="text-sm text-danger">{refused}</p>}
        {invalid && (
          <div className="text-sm text-danger">
            <p>It can’t run yet:</p>
            <ul className="list-disc pl-5 text-xs">
              {invalid.map((i, n) => (
                <li key={n}>{i.message}</li>
              ))}
            </ul>
          </div>
        )}
        {shown && preview.data && trials.length === 0 && !preview.error && (
          <p className="text-sm text-fg-muted">
            There are no {label} records to try it on yet.
          </p>
        )}
        {trials.length > 0 && (
          <div
            role="status"
            className={`space-y-2 ${busy ? 'opacity-60' : ''}`}
          >
            <p className="text-sm">
              {failing > 0 ? `Fails on ${failing} of ${trials.length}. ` : ''}
              {changing > 0
                ? `Would change ${changing === trials.length ? 'every one' : `${changing} of ${trials.length}`}.`
                : failing === 0
                  ? 'Would change none of them.'
                  : ''}{' '}
              <span className="text-fg-muted">Nothing is kept.</span>
            </p>
            {trials.map((t) => (
              <Disclosure
                key={t.record_id}
                defaultOpen={trials.length === 1}
                summary={
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span className="flex items-center gap-2 font-medium">
                      {t.name || t.record_id.slice(0, 8)}
                      {changed.has(t.record_id) && (
                        <Badge variant="accent">Changed</Badge>
                      )}
                    </span>
                    <span className="text-xs">
                      <Brief trial={t} plugins={plugins} />
                    </span>
                  </span>
                }
              >
                <div className="p-3">
                  {t.result ? (
                    <Outcome result={t.result} plugins={plugins} />
                  ) : (
                    <p className="text-sm text-fg-muted">{t.problem}</p>
                  )}
                  <p className="mt-2 text-xs">
                    <RecordLink id={t.record_id} fallback="Open the record" />
                  </p>
                </div>
              </Disclosure>
            ))}
            {after?.(failing === 0)}
          </div>
        )}
      </div>
    </Card>
  )
}
