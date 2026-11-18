import { useState } from 'react'
import type { Field as SchemaField } from '../../api/schemas'
import type {
  TrialRecordChange,
  TrialResult,
  WorkflowInput,
} from '../../api/workflows'
import type { PluginInfo } from '../../api/plugins'
import { ApiError } from '../../api/client'
import { useTryWorkflow } from '../../hooks/useWorkflows'
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
import { RecordSearchPicker } from '../records/RecordSearchPicker'
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
  /** Called when the server refuses the YAML itself, with its problems
   * (they are listed here too). */
  onInvalid?: (issues: WorkflowValidationIssue[]) => void
  /** Shown beside the outcome: e.g. a "Turn it on" button. */
  after?: (result: TrialResult) => React.ReactNode
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
            : 'It would change nothing.'}{' '}
          <span className="text-fg-muted">Nothing was kept.</span>
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

/** Try the workflow on a record of the person's choosing: it runs for real
 * and is undone, and what it would have done is shown. */
export function TrialPanel({
  content,
  schema,
  inputs,
  plugins,
  onInvalid,
  after,
}: Props) {
  const [recordId, setRecordId] = useState<string | undefined>()
  const [files, setFiles] = useState<Record<string, File[]>>({})
  const trial = useTryWorkflow()
  const fileInputs = Object.entries(inputs).filter(
    ([, i]) => i.type === 'files',
  )
  const result = trial.data
  const invalid =
    trial.error instanceof ApiError && Array.isArray(trial.error.detail)
      ? (trial.error.detail as WorkflowValidationIssue[])
      : null
  const refused = trial.error && !invalid ? trial.error.message : null

  function go() {
    if (!recordId) return
    trial.mutate(
      { content, recordId, files },
      {
        onError: (err) => {
          if (err instanceof ApiError && Array.isArray(err.detail))
            onInvalid?.(err.detail as WorkflowValidationIssue[])
        },
      },
    )
  }

  return (
    <Card
      title="Try it"
      info="Runs it on the record you choose, then undoes everything it did, and shows what it would have done. A plugin of yours that reaches outside civex (a web request, a file of its own) still does that for real."
    >
      <div className="space-y-3">
        {!schema ? (
          <p className="text-sm text-fg-muted">
            Choose the kind of record it runs on first.
          </p>
        ) : (
          <>
            <Field label={`On which ${schema}?`}>
              <RecordSearchPicker
                schemaName={schema}
                value={recordId}
                onChange={setRecordId}
                placeholder={`Search ${schema} records`}
              />
            </Field>
            {fileInputs.map(([name, decl]) => (
              <Field key={name} label={decl.label || 'Files'}>
                <FileDropZone
                  multiple
                  inputLabel={`${decl.label || name}: choose files`}
                  onFiles={(chosen) =>
                    setFiles((prev) => ({ ...prev, [name]: chosen }))
                  }
                >
                  {files[name]?.length
                    ? `${files[name].length} file${files[name].length === 1 ? '' : 's'} chosen`
                    : undefined}
                </FileDropZone>
              </Field>
            ))}
            <div className="flex items-center gap-2">
              <Button
                variant="primary"
                disabled={!recordId || trial.isPending}
                onClick={go}
              >
                {trial.isPending ? 'Trying…' : result ? 'Try again' : 'Try it'}
              </Button>
              {result && after?.(result)}
            </div>
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
        {result && !trial.isPending && (
          <Outcome result={result} plugins={plugins} />
        )}
      </div>
    </Card>
  )
}
