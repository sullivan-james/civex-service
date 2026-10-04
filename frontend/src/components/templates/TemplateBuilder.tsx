import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { schemasApi } from '../../api/schemas'
import { Chip, Input, Select, Tooltip } from '../ui'
import {
  NON_NAMEABLE,
  formatsFor,
  insertAt,
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

/** Variables the server fills in itself, per kind of template. */
const BUILTINS: Record<'record' | 'file', { name: string; hint: string }[]> = {
  record: [
    { name: 'schema', hint: "this record type's name" },
    { name: 'id', hint: "the record's short id" },
  ],
  file: [
    { name: 'schema', hint: "this record type's name" },
    { name: 'id', hint: "the record's short id" },
    { name: 'ext', hint: "the file's extension" },
  ],
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}

/**
 * Edits a name template: text with `{variable}` or `{variable:format}` in it.
 * Variables are added at the cursor from the chips, each variable's format is
 * picked from a list suited to its type, and the result is previewed by the
 * server (so the preview can't disagree with what's saved).
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
  const nameable = useMemo(
    () => fields.filter((f) => !NON_NAMEABLE.has(f.dtype)),
    [fields],
  )
  const builtins = BUILTINS[kind]

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

  // Another record's values are only usable in a record's name, not a file's.
  const reaches = useMemo(
    () =>
      kind === 'record'
        ? fields
            .filter((f) => f.dtype === 'reference')
            .filter((f) => f.reach?.some((r) => !NON_NAMEABLE.has(r.dtype)))
            .map((f) => ({
              field: f,
              fields: (f.reach ?? []).filter((r) => !NON_NAMEABLE.has(r.dtype)),
            }))
        : [],
    [kind, fields],
  )

  // Chips, grouped by where each value comes from.
  const groups = useMemo(() => {
    const out: {
      title: string
      items: {
        insert: string
        label: string
        title: string
        mono?: boolean
      }[]
    }[] = []
    const add = (title: string, items: (typeof out)[number]['items']) => {
      if (items.length) out.push({ title, items })
    }
    const asItem = (f: TemplateField, prefix = '') => ({
      insert: `${prefix}${f.name}`,
      label: f.label,
      title: `{${prefix}${f.name}}`,
    })
    add(
      'This type',
      nameable.filter((f) => !f.source).map((f) => asItem(f)),
    )
    for (const source of new Set(
      nameable.flatMap((f) => (f.source ? [f.source] : [])),
    ))
      add(
        `From ${source}`,
        nameable.filter((f) => f.source === source).map((f) => asItem(f)),
      )
    for (const r of reaches)
      add(
        `Via ${r.field.label}`,
        r.fields.map((f) => asItem(f, `${r.field.name}.`)),
      )
    add(
      'Built in',
      builtins.map((b) => ({
        insert: b.name,
        label: `{${b.name}}`,
        title: b.hint,
        mono: true,
      })),
    )
    return out
  }, [nameable, reaches, builtins])

  const variables = variablesIn(value)
  const dtypeOf = (name: string) => {
    const [base, sub] = name.split('.')
    if (!sub) return nameable.find((f) => f.name === name)?.dtype
    return reaches
      .find((r) => r.field.name === base)
      ?.fields.find((f) => f.name === sub)?.dtype
  }

  const sample = useMemo(() => {
    const own = nameable.map((f) => [f.name, sampleValue(f.dtype, f.label)])
    const reached = reaches.flatMap((r) =>
      r.fields.map((f) => [
        `${r.field.name}.${f.name}`,
        sampleValue(f.dtype, f.label),
      ]),
    )
    return Object.fromEntries([...own, ...reached])
  }, [nameable, reaches])
  const template = useDebounced(value, 300)
  const preview = useQuery({
    queryKey: ['name-preview', schemaName, kind, template],
    queryFn: () =>
      schemasApi.previewName(schemaName, { template, values: sample, kind }),
    enabled: !!template.trim(),
    placeholderData: (previous) => previous,
  })

  return (
    <div className="space-y-2 min-w-0">
      <Input
        ref={input}
        value={value}
        placeholder={placeholder}
        aria-label={label}
        onChange={(e) => onChange(e.target.value.replace(/[\r\n]+/g, ''))}
        className="!h-12 w-full !px-4 !text-base font-mono"
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

      <div className="space-y-1" role="group" aria-label="Add a value">
        {groups.map((g) => (
          <div key={g.title} className="flex flex-wrap items-center gap-1">
            <span className="w-28 shrink-0 truncate text-xs text-fg-subtle">
              {g.title}
            </span>
            {g.items.map((item) => (
              <Tooltip key={item.insert} content={item.title ?? item.label}>
                <Chip
                  className={item.mono ? 'font-mono text-fg-muted' : ''}
                  onClick={() => insert(item.insert)}
                >
                  {item.label}
                </Chip>
              </Tooltip>
            ))}
          </div>
        ))}
      </div>

      {variables.length > 0 && (
        <ul className="space-y-1">
          {variables.map((v, i) => {
            const choices = formatsFor(dtypeOf(v.name))
            const custom = v.spec && !choices.some((c) => c.spec === v.spec)
            return (
              <li
                key={`${v.start}`}
                className="flex items-center gap-2 text-xs"
              >
                <span className="w-32 truncate font-mono text-fg-muted">
                  {v.name}
                </span>
                <Select
                  size="sm"
                  aria-label={`Format for ${v.name}`}
                  value={v.spec ?? ''}
                  onChange={(e) =>
                    onChange(
                      setVariableFormat(value, i, e.target.value || null),
                    )
                  }
                  className="max-w-56"
                >
                  {choices.map((c) => (
                    <option key={c.spec ?? 'none'} value={c.spec ?? ''}>
                      {c.label}
                    </option>
                  ))}
                  {custom && <option value={v.spec ?? ''}>{v.spec}</option>}
                </Select>
              </li>
            )
          })}
        </ul>
      )}

      <p
        className={`text-xs ${preview.data?.error ? 'text-danger' : 'text-fg-muted'}`}
        role="status"
      >
        {!template.trim()
          ? null
          : preview.data?.error
            ? preview.data.error
            : preview.data
              ? `e.g. ${preview.data.name ?? '(nothing — every value is empty)'}`
              : null}
      </p>
    </div>
  )
}
