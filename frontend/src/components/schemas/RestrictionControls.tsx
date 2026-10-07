import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useRangeSelect } from '../../hooks/useRangeSelect'
import type {
  Field as SchemaField,
  RestrictionDescriptor,
  Schema,
} from '../../api/schemas'
import {
  Button,
  Checkbox,
  Chip,
  InfoTip,
  Input,
  Select,
  TimeZoneSelect,
  Tooltip,
} from '../ui'
import { LocatorMap } from '../ui/LocatorMap'
import {
  zonedLocalToUTC,
  utcToZonedLocal,
  knownTimeZone,
} from '../../utils/dates'
import { ACCEPT_PRESETS, buildAccept, parseAccept } from '../../utils/accept'
import { GEOMETRY_TYPES } from '../../utils/geo'
import {
  PRECISIONS,
  isValidPartialDate,
  placeholderFor,
  type Precision,
} from '../../utils/partialDates'
import { UNIT_GROUPS, canonicalUnit } from '../../utils/units'
import { displayLabel } from '../../utils/naming'
import {
  TemplateBuilder,
  type TemplateField,
} from '../templates/TemplateBuilder'

export type Rules = Record<string, unknown>

/** What a control may need to know about the field it is editing. */
export interface ControlContext {
  schemaName: string
  /** The schema's fields, for the file-name template. */
  fields: TemplateField[]
  schemas: Schema[]
  /** The field as saved, when editing (not creating). */
  existing?: SchemaField
}

export interface ControlProps {
  desc: RestrictionDescriptor
  rules: Rules
  /** Set a rule; `undefined` removes it. */
  set: (key: string, value: unknown) => void
  /** Report (or clear, with null) why this rule can't be saved yet. */
  problem: (key: string, message: string | null) => void
  ctx: ControlContext
}

/** Label, optional help and error around a control made of several inputs. */
function Shell({
  label,
  help,
  error,
  children,
}: {
  label: string
  help?: string
  error?: string | null
  children: ReactNode
}) {
  return (
    <fieldset className="space-y-1.5 min-w-0">
      <legend className="flex items-center gap-1 text-sm font-medium text-fg-muted">
        {label}
        {help && <InfoTip>{help}</InfoTip>}
      </legend>
      {children}
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
    </fieldset>
  )
}

export function NumberControl({ desc, rules, set }: ControlProps) {
  const whole = desc.control === 'integer'
  const stored = rules[desc.key]
  const [text, setText] = useState(stored === undefined ? '' : String(stored))
  return (
    <Shell label={desc.label} help={desc.help}>
      <Input
        size="sm"
        type="number"
        step={whole ? '1' : 'any'}
        min={whole ? 1 : undefined}
        value={text}
        placeholder="none"
        aria-label={desc.label}
        onChange={(e) => {
          setText(e.target.value)
          const n = whole
            ? parseInt(e.target.value, 10)
            : parseFloat(e.target.value)
          set(
            desc.key,
            e.target.value === '' || Number.isNaN(n) ? undefined : n,
          )
        }}
        className="w-40"
      />
    </Shell>
  )
}

const BYTE_UNITS = [
  { label: 'B', size: 1 },
  { label: 'KB', size: 1024 },
  { label: 'MB', size: 1024 ** 2 },
  { label: 'GB', size: 1024 ** 3 },
]

export function BytesControl({ desc, rules, set }: ControlProps) {
  const stored =
    typeof rules[desc.key] === 'number' ? (rules[desc.key] as number) : null
  const initialUnit =
    stored === null
      ? 'MB'
      : ([...BYTE_UNITS]
          .reverse()
          .find((u) => stored % u.size === 0 && stored >= u.size)?.label ?? 'B')
  const [unit, setUnit] = useState(initialUnit)
  const size = BYTE_UNITS.find((u) => u.label === unit)!.size
  const [text, setText] = useState(stored === null ? '' : String(stored / size))
  function emit(nextText: string, nextUnit: string) {
    const n = parseFloat(nextText)
    const mult = BYTE_UNITS.find((u) => u.label === nextUnit)!.size
    set(
      desc.key,
      nextText === '' || Number.isNaN(n) || n <= 0
        ? undefined
        : Math.round(n * mult),
    )
  }
  return (
    <Shell label={desc.label} help={desc.help}>
      <div className="flex items-center gap-2">
        <Input
          size="sm"
          type="number"
          step="any"
          min="0"
          value={text}
          placeholder="no limit"
          aria-label={desc.label}
          onChange={(e) => {
            setText(e.target.value)
            emit(e.target.value, unit)
          }}
          className="w-32"
        />
        <Select
          size="sm"
          value={unit}
          aria-label={`${desc.label} unit`}
          onChange={(e) => {
            setUnit(e.target.value)
            emit(text, e.target.value)
          }}
          className="w-20"
        >
          {BYTE_UNITS.map((u) => (
            <option key={u.label}>{u.label}</option>
          ))}
        </Select>
      </div>
    </Shell>
  )
}

export function ChoicesControl({ desc, rules, set }: ControlProps) {
  const choices = Array.isArray(rules[desc.key])
    ? (rules[desc.key] as string[])
    : []
  const [text, setText] = useState('')
  function add() {
    const incoming = text
      .split(',')
      .map((c) => c.trim())
      .filter((c) => c && !choices.includes(c))
    setText('')
    if (incoming.length) set(desc.key, [...choices, ...incoming])
  }
  return (
    <Shell label={desc.label} help={desc.help}>
      {choices.length > 0 && (
        <ul className="flex flex-wrap gap-1.5">
          {choices.map((c) => (
            <li key={c}>
              <Chip
                removeLabel={`Remove ${c}`}
                onRemove={() => {
                  const rest = choices.filter((x) => x !== c)
                  set(desc.key, rest.length ? rest : undefined)
                }}
              >
                {c}
              </Chip>
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-center gap-2">
        <Input
          size="sm"
          value={text}
          placeholder="Add a value, then press Enter"
          aria-label="New allowed value"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add()
            }
          }}
          className="max-w-xs"
        />
        <Button size="sm" onClick={add} disabled={!text.trim()}>
          Add
        </Button>
      </div>
    </Shell>
  )
}

export function AcceptControl({ desc, rules, set }: ControlProps) {
  const accept =
    typeof rules[desc.key] === 'string' ? (rules[desc.key] as string) : ''
  const parsed = parseAccept(accept)
  const [custom, setCustom] = useState(parsed.custom)
  const apply = (presets: string[], extra: string) =>
    set(desc.key, buildAccept(presets, extra) || undefined)
  return (
    <Shell label={desc.label} help={desc.help}>
      <div className="flex flex-wrap gap-1.5">
        {ACCEPT_PRESETS.map((p) => {
          const on = parsed.presets.includes(p.key)
          return (
            <Tooltip key={p.key} content={p.tokens.join(', ')}>
              <Chip
                selected={on}
                onClick={() =>
                  apply(
                    on
                      ? parsed.presets.filter((k) => k !== p.key)
                      : [...parsed.presets, p.key],
                    custom,
                  )
                }
              >
                {p.label}
              </Chip>
            </Tooltip>
          )
        })}
      </div>
      <Input
        size="sm"
        value={custom}
        placeholder="Other extensions, e.g. .nc, .h5"
        aria-label="Other file extensions"
        onChange={(e) => {
          setCustom(e.target.value)
          apply(parsed.presets, e.target.value)
        }}
        className="max-w-xs"
      />
    </Shell>
  )
}

export function FilenameTemplateControl({
  desc,
  rules,
  set,
  ctx,
}: ControlProps) {
  const value =
    typeof rules[desc.key] === 'string' ? (rules[desc.key] as string) : ''
  return (
    <Shell label={desc.label} help={desc.help}>
      <TemplateBuilder
        schemaName={ctx.schemaName}
        kind="file"
        value={value}
        onChange={(next) => set(desc.key, next || undefined)}
        fields={ctx.fields.filter((f) => f.name !== ctx.existing?.name)}
        label={desc.label}
        placeholder="Keep the original name"
      />
    </Shell>
  )
}

export function SchemaControl({
  desc,
  rules,
  set,
  problem,
  ctx,
}: ControlProps) {
  const value =
    typeof rules[desc.key] === 'string' ? (rules[desc.key] as string) : ''
  useEffect(() => {
    problem(desc.key, value ? null : 'Pick the type of record this links to.')
    return () => problem(desc.key, null)
  }, [value, desc.key, problem])
  return (
    <Shell label={desc.label} help={desc.help}>
      <Select
        size="sm"
        value={value}
        aria-label={desc.label}
        onChange={(e) => set(desc.key, e.target.value || undefined)}
        className="max-w-xs"
      >
        <option value="">— choose a record type —</option>
        {ctx.schemas
          .filter((s) => s.name !== ctx.schemaName)
          .map((s) => (
            <option key={s.id} value={s.name}>
              {displayLabel(s.name, s.label)}
            </option>
          ))}
      </Select>
    </Shell>
  )
}

export function TimezoneControl({ desc, rules, set }: ControlProps) {
  const value =
    typeof rules[desc.key] === 'string' ? (rules[desc.key] as string) : ''
  return (
    <Shell label={desc.label} help={desc.help}>
      <TimeZoneSelect
        size="sm"
        value={value}
        aria-label={desc.label}
        onChange={(tz) => set(desc.key, tz || undefined)}
        unsetLabel="Inherit from the collection"
      />
    </Shell>
  )
}

export function DateBoundControl({ desc, rules, set, problem }: ControlProps) {
  const stored =
    typeof rules[desc.key] === 'string' ? (rules[desc.key] as string) : ''
  const precision = (rules.precision as Precision | undefined) ?? 'day'
  const bad = stored !== '' && !isValidPartialDate(stored)
  useEffect(() => {
    problem(
      desc.key,
      bad
        ? `${desc.label}: use a year, month or day, such as 2020, 2020-03 or 2020-03-14.`
        : null,
    )
    return () => problem(desc.key, null)
  }, [bad, desc.key, desc.label, problem])
  return (
    <Shell
      label={desc.label}
      help={desc.help}
      error={bad ? 'Not a valid date.' : null}
    >
      <Input
        size="sm"
        value={stored}
        placeholder={placeholderFor(precision)}
        aria-label={desc.label}
        onChange={(e) => set(desc.key, e.target.value.trim() || undefined)}
        className="w-56"
      />
    </Shell>
  )
}

/** A date and time typed as wall time in the field's zone, stored as UTC. */
export function DatetimeBoundControl({
  desc,
  rules,
  set,
  problem,
}: ControlProps) {
  const zoneName = typeof rules.timezone === 'string' ? rules.timezone : ''
  const zone = knownTimeZone(zoneName)
  const stored =
    typeof rules[desc.key] === 'string' ? (rules[desc.key] as string) : ''
  const [local, setLocal] = useState(
    stored ? utcToZonedLocal(stored, zone) : '',
  )
  const unresolved = local !== '' && zonedLocalToUTC(local, zone) === null
  const first = useRef(true)
  useEffect(() => {
    // Typed wall time is what the person means; if the zone changes, the
    // instant it stands for changes with it.
    if (first.current) {
      first.current = false
      return
    }
    set(
      desc.key,
      local ? (zonedLocalToUTC(local, zone) ?? undefined) : undefined,
    )
  }, [local, zone, desc.key, set])
  useEffect(() => {
    problem(
      desc.key,
      unresolved
        ? `${desc.label}: that time doesn't exist or is ambiguous in ${zone ?? 'your timezone'} (a clock change). Pick another time.`
        : null,
    )
    return () => problem(desc.key, null)
  }, [unresolved, zone, desc.key, desc.label, problem])
  return (
    <Shell
      label={desc.label}
      error={unresolved ? "That time doesn't exist in this zone." : null}
    >
      <Input
        size="sm"
        type="datetime-local"
        step={1}
        value={local}
        aria-label={desc.label}
        onChange={(e) => setLocal(e.target.value)}
        className="w-56"
      />
    </Shell>
  )
}

export function UnitControl({ desc, rules, set, ctx }: ControlProps) {
  const value =
    typeof rules[desc.key] === 'string' ? (rules[desc.key] as string) : ''
  const saved = ctx.existing?.restrictions?.unit
  const relabelling =
    typeof saved === 'string' && saved !== '' && canonicalUnit(value) !== saved
  return (
    <Shell label={desc.label} help={desc.help}>
      <Input
        size="sm"
        list="restriction-units"
        value={value}
        placeholder="none (plain number)"
        aria-label={desc.label}
        onChange={(e) =>
          set(desc.key, e.target.value.trim() ? e.target.value : undefined)
        }
        className="w-48"
      />
      <datalist id="restriction-units">
        {Object.entries(UNIT_GROUPS).flatMap(([dim, units]) =>
          units.map((u) => (
            <option key={u} value={u}>
              {dim}
            </option>
          )),
        )}
      </datalist>
      {relabelling && (
        <p role="alert" className="text-xs text-warning">
          Relabels {String(saved)} as {value.trim() || 'none'}: stored values
          are not converted. For a different unit, add a new field.
        </p>
      )}
    </Shell>
  )
}

export function PrecisionControl({ desc, rules, set }: ControlProps) {
  const value = (rules[desc.key] as Precision | undefined) ?? 'day'
  return (
    <Shell label={desc.label} help={desc.help}>
      <Select
        size="sm"
        value={value}
        aria-label={desc.label}
        // 'day' is what a field without the key already means.
        onChange={(e) =>
          set(desc.key, e.target.value === 'day' ? undefined : e.target.value)
        }
        className="w-40"
      >
        {PRECISIONS.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </Select>
    </Shell>
  )
}

export function GeometryTypesControl({ desc, rules, set }: ControlProps) {
  const chosen = Array.isArray(rules[desc.key])
    ? (rules[desc.key] as string[])
    : []
  const range = useRangeSelect(GEOMETRY_TYPES)
  return (
    <Shell label={desc.label} help={desc.help}>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {GEOMETRY_TYPES.map((g) => (
          <label
            key={g}
            onClick={range.onClick}
            className="flex select-none items-center gap-1.5 text-sm"
          >
            <Checkbox
              checked={chosen.includes(g)}
              onClick={range.onClick}
              onChange={(e) => {
                // Shift-click takes every type between the last one clicked and
                // this one, in the order shown.
                const ids = range.rangeFor(g) ?? [g]
                const next = e.target.checked
                  ? [...chosen, ...ids.filter((t) => !chosen.includes(t))]
                  : chosen.filter((t) => !ids.includes(t))
                set(desc.key, next.length ? next : undefined)
              }}
            />
            {g}
          </label>
        ))}
      </div>
    </Shell>
  )
}

const EDGES = ['west', 'south', 'east', 'north'] as const

export function BboxControl({ desc, rules, set, problem }: ControlProps) {
  const stored = Array.isArray(rules[desc.key])
    ? (rules[desc.key] as number[])
    : null
  const [edges, setEdges] = useState<string[]>(
    stored ? stored.map(String) : ['', '', '', ''],
  )
  const filled = edges.filter((e) => e.trim() !== '')
  const nums = edges.map((e) => (e.trim() === '' ? NaN : Number(e)))
  let error: string | null = null
  if (filled.length > 0 && filled.length < 4)
    error = 'Fill in west, south, east and north, or clear all four.'
  else if (filled.length === 4) {
    if (nums.some(Number.isNaN)) error = 'Edges must be numbers in degrees.'
    else if (Math.abs(nums[0]) > 180 || Math.abs(nums[2]) > 180)
      error = 'Longitudes must be between -180 and 180.'
    else if (nums[1] < -90 || nums[3] > 90 || nums[1] > nums[3])
      error = 'Latitudes must be between -90 and 90, with south below north.'
  }
  useEffect(() => {
    problem(desc.key, error ? `${desc.label}: ${error}` : null)
    return () => problem(desc.key, null)
  }, [error, desc.key, desc.label, problem])
  const valid = filled.length === 4 && !error
  return (
    <Shell label={desc.label} help={desc.help} error={error}>
      <div className="flex flex-wrap items-start gap-4">
        <div className="grid grid-cols-2 gap-2">
          {EDGES.map((edge, i) => (
            <label
              key={edge}
              className="flex flex-col gap-0.5 text-xs text-fg-muted"
            >
              {edge[0].toUpperCase() + edge.slice(1)} (°)
              <Input
                size="sm"
                type="number"
                step="any"
                value={edges[i]}
                placeholder="any"
                onChange={(e) => {
                  const next = edges.map((v, j) =>
                    j === i ? e.target.value : v,
                  )
                  setEdges(next)
                  const all = next.map((v) =>
                    v.trim() === '' ? NaN : Number(v),
                  )
                  set(desc.key, all.some(Number.isNaN) ? undefined : all)
                }}
                className="w-28"
              />
            </label>
          ))}
        </div>
        {valid && <LocatorMap bbox={nums} className="w-56" />}
      </div>
    </Shell>
  )
}
