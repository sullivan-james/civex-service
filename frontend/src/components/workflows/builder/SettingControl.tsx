import { useState } from 'react'
import type { Schema } from '../../../api/schemas'
import type { Collection } from '../../../api/collections'
import { Button, Checkbox, Field, Input, Select, Textarea } from '../../ui'
import { PatternFromExampleDialog } from '../../files/PatternFromExample'
import { useExampleFilenames } from '../../../hooks/useExampleFilenames'
import { fieldsWithInherited } from '../../../utils/schemaFields'
import { displayLabel } from '../../../utils/naming'
import type { Setting, SettingHint } from '../../../utils/pluginSettings'

/** What a setting's control needs to know beyond its own value: the step's
 * other settings (a field list depends on the schema chosen beside it) and
 * the schema the workflow runs on. */
export interface SettingContext {
  schema: string
  config: Record<string, unknown>
  settings: Setting[]
  schemas: Schema[]
  collections: Collection[]
  /** Whether the workflow asks for files when it is run. */
  takesFiles: boolean
}

interface Props {
  setting: Setting
  value: unknown
  onChange: (value: unknown) => void
  ctx: SettingContext
  /** Set several settings of the step at once (a pattern built from an
   * example also fills its date format). */
  onChangeSome: (values: Record<string, unknown>) => void
  missing?: boolean
}

function str(v: unknown): string {
  return v === undefined || v === null ? '' : String(v)
}

/** The schema a `field` setting lists the fields of: the one in the setting
 * it names (`of`), else the workflow's. */
function schemaFor(hint: SettingHint, ctx: SettingContext): string {
  return hint.of ? str(ctx.config[hint.of]) : ctx.schema
}

function FieldPicker({
  setting,
  value,
  onChange,
  ctx,
  id,
}: Props & { id?: string }) {
  const name = schemaFor(setting.hint, ctx)
  const schema = ctx.schemas.find((s) => s.name === name)
  if (!schema) {
    return (
      <Input
        size="sm"
        id={id}
        value={str(value)}
        placeholder={
          setting.hint.of ? 'Choose the kind of record first' : 'Field key'
        }
        onChange={(e) => onChange(e.target.value)}
      />
    )
  }
  const dtypes = setting.hint.dtypes
  const fields = fieldsWithInherited(schema, ctx.schemas, false).filter(
    (f) => !dtypes || dtypes.includes(f.dtype ?? ''),
  )
  const current = str(value)
  return (
    <Select
      size="sm"
      id={id}
      value={current}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">— choose a field —</option>
      {current && !fields.some((f) => f.name === current) && (
        <option value={current}>
          {current} (not a field of {name})
        </option>
      )}
      {fields.map((f) => (
        <option key={f.name} value={f.name}>
          {f.label}
          {f.source ? ` (from ${f.source})` : ''}
        </option>
      ))}
    </Select>
  )
}

/** The file field the names a pattern reads come from: for a pattern on the
 * names in a field (`on: field`), that field of the workflow's record; for
 * files given at a run (`on: files`), the step's file field, whose existing
 * files are usually named the same way. */
function exampleSource(
  setting: Setting,
  ctx: SettingContext,
): { schema: string; field: string } {
  const on = setting.hint.on
  if (on && on !== 'files')
    return { schema: ctx.schema, field: str(ctx.config[on]) }
  const fileSetting = ctx.settings.find(
    (s) =>
      s.hint.kind === 'field' &&
      (s.hint.dtypes ?? []).some((d) => d === 'file' || d === 'file_list'),
  )
  if (!fileSetting) return { schema: '', field: '' }
  return {
    schema: schemaFor(fileSetting.hint, ctx),
    field: str(ctx.config[fileSetting.key]),
  }
}

function PatternControl(props: Props & { id?: string }) {
  const { setting, value, onChange, ctx, onChangeSome, id } = props
  const [open, setOpen] = useState(false)
  const source = exampleSource(setting, ctx)
  const examples = useExampleFilenames(source.schema, source.field)
  const readAs = setting.hint.read_as
    ? str(ctx.config[setting.hint.read_as]) || 'string'
    : 'string'
  const dateKey = setting.hint.date_format
  const isDate = readAs === 'date' || readAs === 'datetime'
  // For a date the dialog starts from the date format, which is what it tries
  // on the names; the pattern is made from it.
  const initial = isDate && dateKey ? str(ctx.config[dateKey]) : str(value)
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Input
        size="sm"
        id={id}
        value={str(value)}
        className="min-w-0 flex-1 font-mono"
        placeholder="Build it from an example →"
        onChange={(e) => onChange(e.target.value)}
      />
      <Button size="sm" onClick={() => setOpen(true)}>
        Build from an example…
      </Button>
      {open && (
        <PatternFromExampleDialog
          kind={readAs}
          examples={examples}
          dateStyle="separate"
          checkClashes={!!setting.hint.keys}
          initialPattern={initial}
          onApply={(choice) => {
            onChangeSome({
              [setting.key]: choice.pattern,
              ...(dateKey ? { [dateKey]: choice.dateFormat ?? null } : {}),
            })
            setOpen(false)
          }}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  )
}

function Control(props: Props & { id?: string }) {
  const { setting, value, onChange, ctx, id } = props
  const { hint } = setting
  switch (hint.kind) {
    case 'field':
      return <FieldPicker {...props} />
    case 'schema':
      return (
        <Select
          size="sm"
          id={id}
          value={str(value)}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">— choose a kind of record —</option>
          {ctx.schemas.map((s) => (
            <option key={s.id} value={s.name}>
              {displayLabel(s.name, s.label)}
            </option>
          ))}
        </Select>
      )
    case 'collection':
      return (
        <Select
          size="sm"
          id={id}
          value={str(value)}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">The record’s own collection</option>
          {ctx.collections.map((c) => (
            <option key={c.id} value={c.name}>
              {c.name}
            </option>
          ))}
        </Select>
      )
    case 'record':
      return (
        <Input
          size="sm"
          id={id}
          value={str(value)}
          className="font-mono"
          placeholder="The record it runs on"
          onChange={(e) => onChange(e.target.value)}
        />
      )
    case 'choice': {
      const current = str(value === undefined ? setting.default : value)
      const options = hint.choices ?? []
      return (
        <Select
          size="sm"
          id={id}
          value={current}
          onChange={(e) => onChange(e.target.value)}
        >
          {!setting.required && setting.default === undefined && (
            <option value="">—</option>
          )}
          {current && !options.some((o) => o.value === current) && (
            <option value={current}>{current}</option>
          )}
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
      )
    }
    case 'pattern':
      return <PatternControl {...props} />
  }
  switch (setting.type) {
    case 'boolean':
      return (
        <Checkbox
          id={id}
          checked={value === undefined ? !!setting.default : !!value}
          onChange={(e) => onChange(e.target.checked)}
        />
      )
    case 'integer':
    case 'number':
      return (
        <Input
          size="sm"
          id={id}
          type="number"
          value={str(value)}
          placeholder={str(setting.default)}
          onChange={(e) =>
            onChange(e.target.value === '' ? null : Number(e.target.value))
          }
        />
      )
    case 'array':
      return (
        <Input
          size="sm"
          id={id}
          value={Array.isArray(value) ? value.join(', ') : str(value)}
          placeholder="One, another, …"
          onChange={(e) =>
            onChange(
              e.target.value
                .split(',')
                .map((v) => v.trim())
                .filter(Boolean),
            )
          }
        />
      )
    case 'object':
      return <ObjectControl {...props} />
  }
  return (
    <Input
      size="sm"
      id={id}
      value={str(value)}
      placeholder={setting.default ? str(setting.default) : undefined}
      className={hint.kind === 'date_format' ? 'font-mono' : undefined}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}

/** A mapping setting as `key: value` lines; kept as typed until it reads. */
function ObjectControl({ value, onChange, id }: Props & { id?: string }) {
  const initial = Object.entries(
    (value as Record<string, unknown> | null) ?? {},
  )
    .map(([k, v]) => `${k}: ${str(v)}`)
    .join('\n')
  const [draft, setDraft] = useState(initial)
  return (
    <Textarea
      id={id}
      rows={3}
      value={draft}
      className="font-mono text-xs"
      placeholder="column: field"
      onChange={(e) => {
        setDraft(e.target.value)
        const out: Record<string, string> = {}
        for (const line of e.target.value.split('\n')) {
          const at = line.indexOf(':')
          if (at > 0) out[line.slice(0, at).trim()] = line.slice(at + 1).trim()
        }
        onChange(Object.keys(out).length ? out : null)
      }}
    />
  )
}

export function SettingControl(props: Props) {
  const { setting, missing } = props
  return (
    <Field
      label={setting.title}
      info={setting.description || undefined}
      required={setting.required}
      error={missing ? 'Choose this to finish the step.' : undefined}
    >
      <Control {...props} />
    </Field>
  )
}
