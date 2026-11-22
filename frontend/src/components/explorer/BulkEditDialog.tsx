import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  selectionBody,
  type BulkEditPlan,
  type BulkEditRequest,
  type RecordSelection,
} from '../../api/records'
import type { Field as SchemaField, Schema } from '../../api/schemas'
import { useBulkEditPlan } from '../../hooks/useRecords'
import { useDebouncedValue } from '../../hooks/useDebouncedValue'
import { errorMessage } from '../../lib/errors'
import { pluralise } from '../../lib/utils'
import { displayLabel } from '../../utils/naming'
import { bulkEditableFields } from '../../utils/bulkEdit'
import { DynamicField } from '../records/DynamicField'
import { toSaved } from '../records/RecordFieldGrid'
import { editRecords } from './bulkEditFlow'
import {
  Button,
  Field,
  FormError,
  IconButton,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  SegmentedControl,
  Select,
  Spinner,
} from '../ui'
import { Plus, X } from '../ui/icons'
import { useToast } from '../ui/ToastProvider'

type Mode = 'set' | 'clear'
interface Row {
  field: string
  mode: Mode
  draft: unknown
}

/** The changes the rows say, as the API takes them; null while a value is
 * still unusable (half-typed number, say) or a set has no value. */
function changesOf(
  rows: Row[],
  byName: Map<string, SchemaField>,
): Record<string, unknown> | null {
  const changes: Record<string, unknown> = {}
  for (const row of rows) {
    const field = byName.get(row.field)
    if (!field) return null
    if (row.mode === 'clear') {
      changes[row.field] = null
      continue
    }
    const value = toSaved(field, row.draft)
    if (value === null || value === undefined) return null
    changes[row.field] = value
  }
  return Object.keys(changes).length ? changes : null
}

/** Set (or clear) one or more fields on every chosen record at once: the
 * rows ticked, or all N the list matches. Each value is entered with the
 * field's own input; the server's plan (how many change, how many already
 * hold it, which can't and why, how many workflow runs would start) is asked
 * again as the choices settle, and Change is offered only when something
 * would. */
export function BulkEditDialog({
  selection,
  count,
  listed,
  onClose,
  onDone,
}: {
  selection: RecordSelection
  /** How many records are chosen, for the title. */
  count: number
  /** The kind of record listed: its own fields are the ones offered. */
  listed: Schema
  onClose: () => void
  onDone: () => void
}) {
  const fields = useMemo(() => bulkEditableFields(listed), [listed])
  const byName = useMemo(
    () => new Map(fields.map((f) => [f.name, f])),
    [fields],
  )
  const [rows, setRows] = useState<Row[]>(() =>
    fields.length ? [{ field: fields[0].name, mode: 'set', draft: '' }] : [],
  )
  const changes = changesOf(rows, byName)
  // Compared by what it says, not by identity: a body is made each render.
  const bodyKey = changes
    ? JSON.stringify({ ...selectionBody(selection), changes })
    : ''
  const settledKey = useDebouncedValue(bodyKey, 300)
  const settled = useMemo<BulkEditRequest | null>(
    () => (settledKey ? JSON.parse(settledKey) : null),
    [settledKey],
  )
  const plan = useBulkEditPlan(settled)
  const toast = useToast()
  const qc = useQueryClient()
  const kind = displayLabel(listed.name, listed.label)
  const current = settledKey === bodyKey
  const canApply = !!plan.data?.can_apply && current

  function update(i: number, next: Partial<Row>) {
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...next } : r)))
  }
  const unused = fields.filter((f) => !rows.some((r) => r.field === f.name))

  /** The edit runs as a job (the status bar shows how far it has got, and
   * can stop it), so the dialog is done as soon as it is asked for. */
  function confirm() {
    if (!settled) return
    void editRecords({ toast, qc, problem: () => undefined }, settled).then(
      onDone,
    )
    onClose()
  }

  return (
    <Modal onClose={onClose} size="md">
      <ModalHeader onClose={onClose}>
        Edit {pluralise(count, kind.toLowerCase())}
      </ModalHeader>
      <ModalBody>
        <div className="space-y-4">
          {fields.length === 0 && (
            <p className="text-sm text-fg-muted">
              A {kind} has no fields of its own that can be set here.
            </p>
          )}
          {rows.map((row, i) => {
            const field = byName.get(row.field)!
            const label = displayLabel(field.name, field.label)
            return (
              <div
                key={row.field}
                className="space-y-2 rounded-md border border-border p-3"
                data-testid="bulk-edit-row"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Select
                    aria-label="Field"
                    value={row.field}
                    onChange={(e) =>
                      update(i, { field: e.target.value, draft: '' })
                    }
                    className="min-w-0 flex-1"
                  >
                    {[field, ...unused].map((f) => (
                      <option key={f.name} value={f.name}>
                        {displayLabel(f.name, f.label)}
                      </option>
                    ))}
                  </Select>
                  <SegmentedControl<Mode>
                    label={`Set or clear ${label}`}
                    size="sm"
                    value={row.mode}
                    onChange={(mode) => update(i, { mode })}
                    options={[
                      { value: 'set', label: 'Set to' },
                      { value: 'clear', label: 'Clear' },
                    ]}
                  />
                  {rows.length > 1 && (
                    <IconButton
                      icon={X}
                      aria-label={`Don't change ${label}`}
                      onClick={() =>
                        setRows((rs) => rs.filter((_, j) => j !== i))
                      }
                    />
                  )}
                </div>
                {row.mode === 'set' ? (
                  <Field label={label} hideLabel>
                    <DynamicField
                      field={{ ...field, required: false }}
                      value={row.draft}
                      onChange={(draft) => update(i, { draft })}
                    />
                  </Field>
                ) : (
                  <p className="text-sm text-fg-muted">
                    {label} will be emptied on every chosen record.
                  </p>
                )}
              </div>
            )
          })}
          {unused.length > 0 && rows.length > 0 && (
            <Button
              size="sm"
              onClick={() =>
                setRows((rs) => [
                  ...rs,
                  { field: unused[0].name, mode: 'set', draft: '' },
                ])
              }
            >
              <Plus className="h-4 w-4" aria-hidden /> Another field
            </Button>
          )}
          <PlanText
            waiting={!bodyKey}
            loading={!plan.data}
            stale={!current || plan.isFetching}
            error={plan.error}
            plan={plan.data}
          />
        </div>
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose}>Cancel</Button>
        <Button onClick={confirm} disabled={!canApply}>
          {plan.data?.changing && current
            ? `Change ${plan.data.changing.toLocaleString()}`
            : 'Change'}
        </Button>
      </ModalFooter>
    </Modal>
  )
}

function PlanText({
  waiting,
  loading,
  stale,
  error,
  plan,
}: {
  waiting: boolean
  loading: boolean
  stale: boolean
  error: unknown
  plan: BulkEditPlan | undefined
}) {
  if (waiting)
    return (
      <p className="text-sm text-fg-muted">
        Choose a value to see what the edit would do.
      </p>
    )
  if (error) return <FormError message={errorMessage(error)} />
  if (loading || !plan)
    return (
      <p className="flex items-center gap-2 text-sm text-fg-muted">
        <Spinner /> Working out what would change…
      </p>
    )
  return (
    <div
      className={`space-y-2 text-sm ${stale ? 'opacity-60' : ''}`}
      data-testid="bulk-edit-plan"
    >
      <p>
        {plan.changing > 0
          ? `${pluralise(plan.changing, 'record')} would change.`
          : 'Nothing would change.'}
        {plan.unchanged > 0 &&
          ` ${pluralise(plan.unchanged, 'record')} already ${plan.unchanged === 1 ? 'has' : 'have'} ${plan.fields.length === 1 ? 'this value' : 'these values'}.`}
      </p>
      {plan.skipped > 0 && (
        <div className="space-y-1">
          <p className="text-attention">
            {pluralise(plan.skipped, 'record')} can't take{' '}
            {plan.fields.length === 1 ? 'it' : 'them'} and will be left as{' '}
            {plan.skipped === 1 ? 'it is' : 'they are'}:
          </p>
          <ul className="max-h-32 list-disc space-y-0.5 overflow-auto pl-5 text-fg-muted">
            {plan.skipped_records.slice(0, 20).map((s) => (
              <li key={s.record_id}>
                <span className="text-fg">
                  {s.name ?? s.record_id.slice(0, 8)}
                </span>
                : {s.reason}
              </li>
            ))}
            {plan.skipped > Math.min(20, plan.skipped_records.length) && (
              <li>
                and{' '}
                {(
                  plan.skipped - Math.min(20, plan.skipped_records.length)
                ).toLocaleString()}{' '}
                more
              </li>
            )}
          </ul>
        </div>
      )}
      {plan.runs > 0 && (
        <p className="text-attention" role="status">
          {pluralise(plan.runs, 'workflow run')} would start (
          {plan.workflows.map((w) => `“${w}”`).join(', ')}).
        </p>
      )}
      {plan.runs === 0 && plan.automation_paused && (
        <p className="text-fg-muted">
          Automation is paused, so no workflow runs would start.
        </p>
      )}
    </div>
  )
}
