import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { schemasApi } from '../../api/schemas'
import {
  Button,
  Chip,
  IconButton,
  Input,
  ListButton,
  Select,
  Tooltip,
  TriggerPopover,
} from '../ui'
import { Plus, X } from '../ui/icons'
import {
  NON_NAMEABLE,
  formatsFor,
  insertAt,
  removeVariable,
  sampleValue,
  setVariableFormat,
  variablesIn,
} from '../../utils/templates'

export interface TemplateField {
  name: string
  label: string
  dtype: string
  /** The inherited-from schema's label; null for the schema's own fields. */
  source?: string | null
  /** For a reference field: the fields of the record it points at. */
  reach?: TemplateField[]
}

/** One value a template can use: what is written, and how it is shown. */
interface Choice {
  /** Written between the braces. */
  name: string
  /** In the picker, under its group. */
  label: string
  /** Where it is used, with where it comes from ("Species › Common name"). */
  display: string
  group: string
  dtype?: string
  builtin?: boolean
}

/** Variables the server fills in itself. A file's extension isn't one: it is
 * always the file's own, added after the name. */
const BUILTINS = [
  { name: 'schema', label: 'Type name' },
  { name: 'id', label: 'Short record id' },
]

/** Up to this many values are shown as chips; more get a searchable list. */
const INLINE_LIMIT = 8

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}

/** Every value `fields` offers, grouped by where it comes from: this type, each
 * type above it, and each reference (its own or one above) one hop on. */
function choicesFor(fields: TemplateField[]): Choice[] {
  const out: Choice[] = []
  const nameable = (f: TemplateField) => !NON_NAMEABLE.has(f.dtype)
  for (const f of fields.filter(nameable))
    out.push({
      name: f.name,
      label: f.label,
      display: f.source ? `${f.label} (${f.source})` : f.label,
      group: f.source ? `From ${f.source}` : 'This type',
      dtype: f.dtype,
    })
  for (const ref of fields.filter((f) => f.dtype === 'reference'))
    for (const target of (ref.reach ?? []).filter(nameable))
      out.push({
        name: `${ref.name}.${target.name}`,
        label: target.label,
        display: `${ref.label} › ${target.label}`,
        group: ref.source
          ? `Via ${ref.label} (${ref.source})`
          : `Via ${ref.label}`,
        dtype: target.dtype,
      })
  for (const b of BUILTINS)
    out.push({
      name: b.name,
      label: b.label,
      display: b.label,
      group: 'Built in',
      builtin: true,
    })
  return out
}

function grouped(choices: Choice[]) {
  const groups = new Map<string, Choice[]>()
  for (const c of choices)
    groups.set(c.group, [...(groups.get(c.group) ?? []), c])
  return [...groups].map(([title, items]) => ({ title, items }))
}

/** The searchable list of values, for a type with many fields. */
function InsertPicker({
  choices,
  onPick,
}: {
  choices: Choice[]
  onPick: (choice: Choice) => void
}) {
  return (
    <TriggerPopover
      label="Insert a value"
      panelClassName="w-80 rounded-md border border-border bg-canvas shadow-lg"
      trigger={({ open, toggle }) => (
        <Button size="sm" aria-expanded={open} onClick={toggle}>
          <Plus size={14} aria-hidden="true" /> Insert a value
        </Button>
      )}
    >
      {(close) => (
        <PickerPanel
          choices={choices}
          onPick={(c) => {
            onPick(c)
            close()
          }}
        />
      )}
    </TriggerPopover>
  )
}

function PickerPanel({
  choices,
  onPick,
}: {
  choices: Choice[]
  onPick: (choice: Choice) => void
}) {
  const [q, setQ] = useState('')
  const needle = q.trim().toLowerCase()
  const shown = needle
    ? choices.filter((c) =>
        [c.label, c.group, c.name].some((t) =>
          t.toLowerCase().includes(needle),
        ),
      )
    : choices
  return (
    <div>
      <div className="border-b border-border p-2">
        <Input
          size="sm"
          autoFocus
          value={q}
          placeholder="Search fields"
          aria-label="Search values"
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && shown[0]) {
              e.preventDefault()
              onPick(shown[0])
            }
          }}
        />
      </div>
      <div className="max-h-72 overflow-y-auto py-1">
        {shown.length === 0 && (
          <p className="px-3 py-2 text-sm text-fg-muted">Nothing matches.</p>
        )}
        {grouped(shown).map((g) => (
          <div key={g.title} role="group" aria-label={g.title}>
            <div className="px-3 pt-2 pb-1 text-xs font-medium text-fg-subtle">
              {g.title}
            </div>
            {g.items.map((c) => (
              <ListButton
                key={c.name}
                onClick={() => onPick(c)}
                className="flex items-baseline justify-between gap-3"
              >
                <span className="truncate">{c.label}</span>
                <span className="shrink-0 font-mono text-xs text-fg-subtle">
                  {`{${c.name}}`}
                </span>
              </ListButton>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

/**
 * Edits a name template: text with `{variable}` or `{variable:format}` in it.
 * Values are added at the cursor, as chips or (when there are many) from a
 * searchable list grouped by where each comes from; each value in use is a row
 * with its format and a way to take it out; and the result is previewed by the
 * server (so the preview can't disagree with what's saved). A file's name is
 * its stem only: the file always keeps its own extension.
 */
export function TemplateBuilder({
  schemaName,
  kind,
  value,
  onChange,
  fields,
  label,
  placeholder,
}: {
  schemaName: string
  kind: 'record' | 'file'
  value: string
  onChange: (next: string) => void
  /** The schema's fields; types that can't be written into a name are left out. */
  fields: TemplateField[]
  label: string
  placeholder?: string
}) {
  const input = useRef<HTMLInputElement>(null)
  const choices = useMemo(() => choicesFor(fields), [fields])

  // Where to put the cursor once the inserted text has rendered.
  const pendingCursor = useRef<number | null>(null)
  useLayoutEffect(() => {
    if (pendingCursor.current === null) return
    const el = input.current
    el?.focus()
    el?.setSelectionRange(pendingCursor.current, pendingCursor.current)
    pendingCursor.current = null
  }, [value])

  function insert(name: string) {
    const el = input.current
    const start = el?.selectionStart ?? value.length
    const end = el?.selectionEnd ?? value.length
    const next = insertAt(value, start, end, `{${name}}`)
    pendingCursor.current = next.cursor
    onChange(next.value)
  }

  const variables = variablesIn(value)
  const byName = useMemo(
    () => new Map(choices.map((c) => [c.name, c])),
    [choices],
  )

  const sample = useMemo(
    () =>
      Object.fromEntries(
        choices
          .filter((c) => !c.builtin && c.dtype)
          .map((c) => [c.name, sampleValue(c.dtype!, c.label)]),
      ),
    [choices],
  )
  const template = useDebounced(value, 300)
  const preview = useQuery({
    queryKey: ['name-preview', schemaName, kind, template],
    queryFn: () =>
      schemasApi.previewName(schemaName, { template, values: sample, kind }),
    enabled: !!template.trim(),
    placeholderData: (previous) => previous,
  })

  const inline = choices.length <= INLINE_LIMIT

  return (
    <div className="min-w-0 space-y-3">
      <div className="flex min-w-0 items-center gap-2">
        <Input
          ref={input}
          value={value}
          placeholder={placeholder}
          aria-label={label}
          onChange={(e) => onChange(e.target.value.replace(/[\r\n]+/g, ''))}
          className="!h-11 min-w-0 flex-1 !px-3 font-mono"
          // This is a template, not a login or an address: keep browsers and
          // password managers (Dashlane, 1Password, LastPass, Bitwarden) out.
          type="text"
          name="name-template"
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={false}
          data-1p-ignore
          data-lpignore="true"
          data-bwignore
          data-form-type="other"
          data-dashlane-ignore="true"
        />
        {kind === 'file' && (
          <Tooltip content="The file keeps its own extension, added for you">
            <span className="shrink-0 font-mono text-sm text-fg-muted">
              .ext
            </span>
          </Tooltip>
        )}
      </div>

      {inline ? (
        <div className="space-y-1" role="group" aria-label="Add a value">
          {grouped(choices).map((g) => (
            <div key={g.title} className="flex flex-wrap items-center gap-1">
              <span className="w-28 shrink-0 truncate text-xs text-fg-subtle">
                {g.title}
              </span>
              {g.items.map((c) => (
                <Tooltip key={c.name} content={`{${c.name}}`}>
                  <Chip onClick={() => insert(c.name)}>{c.label}</Chip>
                </Tooltip>
              ))}
            </div>
          ))}
        </div>
      ) : (
        <InsertPicker choices={choices} onPick={(c) => insert(c.name)} />
      )}

      {variables.length > 0 && (
        <ul className="divide-y divide-border rounded-md border border-border">
          {variables.map((v, i) => {
            const choice = byName.get(v.name)
            const formats = formatsFor(choice?.dtype)
            const custom = v.spec && !formats.some((c) => c.spec === v.spec)
            const shown = choice?.display ?? v.name
            return (
              <li
                key={`${v.start}`}
                className="flex min-w-0 items-center gap-2 px-3 py-1.5"
              >
                <span
                  className={`min-w-0 flex-1 truncate text-sm ${choice ? 'text-fg' : 'font-mono text-danger'}`}
                  title={`{${v.name}}`}
                >
                  {shown}
                </span>
                {(formats.length > 1 || custom) && (
                  <Select
                    size="sm"
                    aria-label={`Format for ${v.name}`}
                    value={v.spec ?? ''}
                    onChange={(e) =>
                      onChange(
                        setVariableFormat(value, i, e.target.value || null),
                      )
                    }
                    className="max-w-52"
                  >
                    {formats.map((c) => (
                      <option key={c.spec ?? 'none'} value={c.spec ?? ''}>
                        {c.label}
                      </option>
                    ))}
                    {custom && <option value={v.spec ?? ''}>{v.spec}</option>}
                  </Select>
                )}
                <IconButton
                  icon={X}
                  size="sm"
                  onClick={() => onChange(removeVariable(value, i))}
                  aria-label={`Remove ${shown}`}
                />
              </li>
            )
          })}
        </ul>
      )}

      {template.trim() && (preview.data || preview.error) && (
        <p
          role="status"
          className="flex min-w-0 items-baseline gap-2 rounded-md bg-canvas-subtle px-3 py-2 text-sm"
        >
          {preview.data?.error ? (
            <span className="text-danger">{preview.data.error}</span>
          ) : (
            <>
              <span className="shrink-0 text-xs text-fg-subtle">Example</span>
              <span className="min-w-0 truncate font-mono text-fg">
                {preview.data?.name ??
                  (kind === 'file'
                    ? 'every value is empty, so the original name'
                    : 'every value is empty')}
              </span>
            </>
          )}
        </p>
      )}
    </div>
  )
}
