import type { ImportColumn, ImportSheet } from '../../api/imports'
import type { Schema } from '../../api/schemas'
import { displayLabel } from '../../utils/naming'
import {
  Button,
  DataTable,
  Field,
  FormError,
  Input,
  SegmentedControl,
  Select,
} from '../ui'
import {
  IMPORT_TYPES,
  LEAVE_OUT,
  NEW_FIELD,
  matchable,
  type Choices,
  type ColumnSetting,
  type Target,
} from './importPlan'

const NEW_KIND = '__new_kind__'

/** Where each column goes: the kind of record, then one row per column with
 * what it holds and where it should go, and how a row finds the record it
 * stands for. */
export function ColumnsStep({
  choices,
  topLevel,
  onTarget,
  onSheet,
  onSettings,
  onMatch,
  onIfExists,
  problem,
  error,
  onBack,
  onNext,
}: {
  choices: Choices
  topLevel: Schema[]
  onTarget: (t: Target) => void
  onSheet: (name: string) => void
  onSettings: (s: ColumnSetting[]) => void
  onMatch: (heading: string) => void
  onIfExists: (v: Choices['ifExists']) => void
  problem: string | null
  error: string | null
  onBack: () => void
  onNext: () => void
}) {
  const { sheet, target, schema, settings } = choices
  const keys = matchable(sheet.columns, settings, schema)

  function setOne(i: number, patch: Partial<ColumnSetting>) {
    onSettings(settings.map((s, j) => (j === i ? { ...s, ...patch } : s)))
    // A column that is left out, or whose type can't be matched, can't match.
    if (
      patch.goesIn === LEAVE_OUT &&
      choices.match === sheet.columns[i].heading
    )
      onMatch('')
  }

  return (
    <div className="space-y-6">
      <h2 className="text-base font-semibold text-fg">
        Where do the columns go?
      </h2>
      <p className="text-sm text-fg-muted">
        {choices.filename}: {sheet.total.toLocaleString()} rows
      </p>

      <div className="flex flex-wrap items-end gap-4">
        <Field label="Put the rows in">
          <Select
            value={target.kind === 'existing' ? target.name : NEW_KIND}
            onChange={(e) =>
              onTarget(
                e.target.value === NEW_KIND
                  ? { kind: 'new', label: '' }
                  : { kind: 'existing', name: e.target.value },
              )
            }
          >
            {topLevel.map((s) => (
              <option key={s.id} value={s.name}>
                {displayLabel(s.name, s.label)}
              </option>
            ))}
            <option value={NEW_KIND}>A new kind of record</option>
          </Select>
        </Field>
        {target.kind === 'new' && (
          <Field label="Name">
            <Input
              value={target.label}
              onChange={(e) => onTarget({ kind: 'new', label: e.target.value })}
              aria-label="Name of the new kind of record"
            />
          </Field>
        )}
        {sheet.sheets.length > 1 && (
          <Field label="Sheet">
            <Select
              value={sheet.sheet ?? ''}
              onChange={(e) => onSheet(e.target.value)}
            >
              {sheet.sheets.map((name) => (
                <option key={name}>{name}</option>
              ))}
            </Select>
          </Field>
        )}
      </div>

      <DataTable
        layout="auto"
        getRowId={(c) => c.heading}
        rows={sheet.columns}
        columns={[
          {
            key: 'column',
            header: 'Column',
            render: (c) => <span className="font-medium">{c.label}</span>,
          },
          {
            key: 'first',
            header: 'First rows',
            render: (c) => (
              <span className="text-fg-muted">
                {firstRows(sheet, c).join(', ')}
              </span>
            ),
          },
          {
            key: 'goes',
            header: 'Goes in',
            render: (c) => {
              const i = sheet.columns.indexOf(c)
              return (
                <Select
                  size="sm"
                  aria-label={`Where ${c.label} goes`}
                  value={settings[i].goesIn}
                  onChange={(e) => setOne(i, { goesIn: e.target.value })}
                >
                  <option value={NEW_FIELD}>A new field</option>
                  {(schema?.fields ?? []).map((f) => (
                    <option key={f.id} value={f.name}>
                      {displayLabel(f.name, f.label)}
                    </option>
                  ))}
                  <option value={LEAVE_OUT}>Leave out</option>
                </Select>
              )
            },
          },
          {
            key: 'as',
            header: 'As',
            render: (c) => {
              const i = sheet.columns.indexOf(c)
              return settings[i].goesIn === NEW_FIELD ? (
                <Select
                  size="sm"
                  aria-label={`What ${c.label} holds`}
                  value={settings[i].dtype}
                  onChange={(e) => setOne(i, { dtype: e.target.value })}
                >
                  {IMPORT_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </Select>
              ) : null
            },
          },
        ]}
      />

      <div className="space-y-3">
        <Field label="A row is a record already saved when this matches">
          <Select
            value={choices.match}
            onChange={(e) => onMatch(e.target.value)}
          >
            <option value="">Nothing: every row is a new record</option>
            {keys.map((c) => (
              <option key={c.heading} value={c.heading}>
                {c.label}
              </option>
            ))}
          </Select>
        </Field>
        {choices.match && (
          <SegmentedControl
            label="If a matching record is saved"
            value={choices.ifExists === 'add_new' ? 'update' : choices.ifExists}
            onChange={onIfExists}
            options={[
              { value: 'update', label: 'Update it' },
              { value: 'skip', label: 'Leave it' },
            ]}
          />
        )}
      </div>

      <FormError message={error} />
      <div className="flex items-center gap-2">
        <Button onClick={onBack}>Back</Button>
        <Button
          variant="primary"
          onClick={onNext}
          disabled={problem !== null}
          title={problem ?? undefined}
        >
          Check
        </Button>
        {problem && <span className="text-sm text-fg-muted">{problem}</span>}
      </div>
    </div>
  )
}

/** The first few values a column holds, for telling it apart. */
function firstRows(sheet: ImportSheet, column: ImportColumn): string[] {
  const at = sheet.columns.indexOf(column)
  return sheet.rows
    .map((r) => r[at])
    .filter((v) => v !== undefined && v !== '')
    .slice(0, 3)
}
