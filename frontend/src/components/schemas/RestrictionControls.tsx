import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
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
  IconButton,
  InfoTip,
  Input,
  Select,
  Textarea,
  TimeZoneSelect,
  Tooltip,
} from '../ui'
import { LocatorMap } from '../ui/LocatorMap'
import { X } from '../ui/icons'
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
import { FILENAME_FORMAT_TOKENS_HELP } from '../../utils/filenamePattern'
import { DATE_KINDS, fromFilenameRule } from '../../utils/filenameExtract'
import { useFromFilenamePreview } from '../../hooks/useFromFilenamePreview'
import { useExampleFilenames } from '../../hooks/useExampleFilenames'
import { PatternFromExampleDialog } from '../files/PatternFromExample'
import {
  TemplateBuilder,
  ValueInserter,
  choicesFor,
  type TemplateField,
} from '../templates/TemplateBuilder'
import { insertAt } from '../../utils/templates'
import {
  FORMULA_FUNCTIONS,
  FORMULA_RESULTS,
  readableInFormula,
  shownAs,
} from '../../utils/formulas'
import { useFormulaPreview } from '../../hooks/useFormulaPreview'
import { RecordSearchPicker } from '../records/RecordSearchPicker'
import { FieldValue } from '../records/FieldValue'

export type Rules = Record<string, unknown>

/** What a control may need to know about the field it is editing. */
export interface ControlContext {
  schemaName: string
  /** The type of the field being edited (its storage type, e.g. `datetime`). */
  type?: string
  /** The schema's fields (own and inherited), for the file-name template and
   * the file field a value is read from. */
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

/** Which file field's name fills this field, and the pattern that reads it;
 * tried live on a file name. The rule is `{field, pattern}` or nothing. */
export function FromFilenameControl({
  desc,
  rules,
  set,
  problem,
  ctx,
}: ControlProps) {
  const rule = fromFilenameRule(rules)
  const field = rule?.field ?? ''
  // The patterns tried in order; a lone empty row is "no pattern yet".
  const patterns = rule?.patterns.length ? rule.patterns : ['']
  const kind = ctx.type ?? ctx.existing?.type ?? 'string'
  const isDate = DATE_KINDS.has(kind)
  const fileFields = ctx.fields.filter(
    (f) => f.dtype === 'file' || f.dtype === 'file_list',
  )
  const [sample, setSample] = useState('')
  // Which pattern row "Build from an example…" is filling, if any.
  const [building, setBuilding] = useState<number | null>(null)
  const examples = useExampleFilenames(ctx.schemaName, field || null)
  const incomplete = !!field && patterns.some((p) => !p.trim())
  // The server tries the patterns, as the one implementation of them: each
  // row's problem, and what the sample name gives.
  const preview = useFromFilenamePreview(
    sample,
    patterns,
    kind,
    !!field && !incomplete,
  )
  const rowErrors = patterns.map((_, i) =>
    incomplete ? null : (preview.data?.problems[i] ?? null),
  )
  const patternErr = rowErrors.find((e) => e) ?? null
  useEffect(() => {
    problem(
      desc.key,
      incomplete
        ? `${desc.label}: give every pattern, or remove the empty row.`
        : patternErr
          ? `${desc.label}: ${patternErr}.`
          : null,
    )
    return () => problem(desc.key, null)
  }, [incomplete, patternErr, desc.key, desc.label, problem])
  // Stored as the one string when there is one pattern (the simple form),
  // else the list, which is what the server reads either way.
  const update = (nextField: string, nextPatterns: string[]) =>
    set(
      desc.key,
      nextField
        ? {
            field: nextField,
            pattern: nextPatterns.length === 1 ? nextPatterns[0] : nextPatterns,
          }
        : undefined,
    )
  const tried =
    sample && field && !incomplete && !patternErr ? preview.data : null
  return (
    <Shell label={desc.label} help={desc.help}>
      {fileFields.length === 0 ? (
        <p className="text-xs text-fg-subtle">
          Add a file field to this type first.
        </p>
      ) : (
        <Select
          size="sm"
          value={field}
          aria-label="File field"
          onChange={(e) => update(e.target.value, patterns)}
          className="max-w-xs"
        >
          <option value="">— not filled from a file —</option>
          {fileFields.map((f) => (
            <option key={f.name} value={f.name}>
              {f.source ? `${f.label} (${f.source})` : f.label}
            </option>
          ))}
        </Select>
      )}
      {field && (
        <>
          {patterns.map((pattern, i) => {
            const label = patterns.length > 1 ? `Pattern ${i + 1}` : 'Pattern'
            return (
              <div key={i} className="space-y-1">
                <div className="flex items-center gap-2">
                  <Input
                    size="sm"
                    value={pattern}
                    aria-label={label}
                    placeholder={
                      isDate ? 'YYYYMMDD[-_]HHmmSS' : 'site-([A-Z]+)_'
                    }
                    onChange={(e) =>
                      update(
                        field,
                        patterns.map((p, j) => (j === i ? e.target.value : p)),
                      )
                    }
                    className="max-w-md font-mono"
                  />
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setBuilding(i)}
                  >
                    Build from an example…
                  </Button>
                  {patterns.length > 1 && (
                    <IconButton
                      icon={X}
                      aria-label={`Remove pattern ${i + 1}`}
                      onClick={() =>
                        update(
                          field,
                          patterns.filter((_, j) => j !== i),
                        )
                      }
                    />
                  )}
                </div>
                {rowErrors[i] && (
                  <p role="alert" className="text-xs text-danger">
                    {rowErrors[i]}
                  </p>
                )}
              </div>
            )
          })}
          <Button
            size="sm"
            variant="ghost"
            onClick={() => update(field, [...patterns, ''])}
            disabled={incomplete}
          >
            Add another pattern
          </Button>
          <p className="text-xs text-fg-subtle">
            {isDate
              ? `Tokens: ${FILENAME_FORMAT_TOKENS_HELP}. Anything else is a regular expression, so [-_] takes a dash or an underscore. Or a regular expression with named groups (?P<year>…), (?P<month>…), (?P<day>…), (?P<hour>…), (?P<minute>…), (?P<second>…).`
              : 'A regular expression. The first capture group ( ) is the value, or the whole match without one.'}{' '}
            A pattern needn't describe the whole name. With several, the first
            that matches is used.
          </p>
          <Input
            size="sm"
            value={sample}
            aria-label="Try a file name"
            placeholder="Try it on a file name, e.g. 20240315_093000.wav"
            onChange={(e) => setSample(e.target.value)}
            className="max-w-md"
          />
          {tried && (
            <p role="status" data-testid="tried" className="text-xs">
              {tried.error ? (
                <span className="text-danger">
                  Matches, but {tried.error}: the record would be refused.
                </span>
              ) : tried.value === null ? (
                <span className="text-fg-subtle">
                  No match: the field would stay blank.
                </span>
              ) : (
                <span className="text-fg-muted">
                  Gives{' '}
                  <code className="rounded-md border border-border bg-canvas px-1.5 py-0.5 font-mono">
                    {String(tried.value)}
                  </code>
                </span>
              )}
            </p>
          )}
        </>
      )}
      {building !== null && (
        <PatternFromExampleDialog
          kind={kind}
          examples={[...(sample ? [sample] : []), ...examples]}
          dateStyle="token"
          initialPattern={patterns[building] || undefined}
          onApply={({ pattern }) => {
            update(
              field,
              patterns.map((p, j) => (j === building ? pattern : p)),
            )
            setBuilding(null)
          }}
          onClose={() => setBuilding(null)}
        />
      )}
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
        <option value="">— choose a schema —</option>
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

/** A formula's expression: a monospace box, the fields it can read and the
 * functions it can call put in at the cursor, and what it gives worked out by
 * the server for a record of the kind (the latest, or one picked), with the
 * same check saving makes, so a formula that can't be saved says why here. */
export function FormulaControl({
  desc,
  rules,
  set,
  problem,
  ctx,
}: ControlProps) {
  const value =
    typeof rules[desc.key] === 'string' ? (rules[desc.key] as string) : ''
  const box = useRef<HTMLTextAreaElement>(null)
  const pendingCursor = useRef<number | null>(null)
  const [recordId, setRecordId] = useState<string | undefined>()
  useLayoutEffect(() => {
    if (pendingCursor.current === null) return
    box.current?.focus()
    box.current?.setSelectionRange(pendingCursor.current, pendingCursor.current)
    pendingCursor.current = null
  }, [value])

  const self = ctx.existing?.name
  const choices = useMemo(
    () =>
      choicesFor(
        ctx.fields.filter((f) => f.name !== self),
        {
          usable: (f) => readableInFormula(f.dtype),
          // A link reaches stored values only, one step.
          reachable: (f) => readableInFormula(f.dtype) && f.dtype !== 'formula',
          builtins: false,
        },
      ),
    [ctx.fields, self],
  )

  function insert(snippet: string, back = 0) {
    const el = box.current
    const next = insertAt(
      value,
      el?.selectionStart ?? value.length,
      el?.selectionEnd ?? value.length,
      snippet,
    )
    pendingCursor.current = next.cursor - back
    set(desc.key, next.value || undefined)
  }

  const result = typeof rules.result === 'string' ? rules.result : null
  const decimals = typeof rules.decimals === 'number' ? rules.decimals : null
  const preview = useFormulaPreview(ctx.schemaName, {
    expression: value,
    result,
    decimals,
    field: self ?? null,
    record_id: recordId ?? null,
  })
  const data = value.trim() ? preview.data : undefined
  const refused = data?.problem ?? null
  useEffect(() => {
    problem(desc.key, value.trim() ? refused : null)
  }, [desc.key, problem, refused, value])

  return (
    <Shell label={desc.label} help={desc.help}>
      <Textarea
        ref={box}
        value={value}
        rows={3}
        placeholder="mass / height ** 2"
        aria-label={desc.label}
        invalid={!!refused}
        spellCheck={false}
        autoComplete="off"
        className="w-full font-mono"
        onChange={(e) => set(desc.key, e.target.value || undefined)}
      />
      <ValueInserter
        choices={choices}
        written={(name) => name}
        onPick={(c) => insert(c.name)}
      />
      <Select
        size="sm"
        value=""
        aria-label="Insert a function"
        className="w-56"
        onChange={(e) => {
          const fn = FORMULA_FUNCTIONS.find((f) => f.name === e.target.value)
          if (!fn) return
          // The cursor goes inside the brackets, where the first value goes.
          insert(fn.insert, fn.insert.length - fn.insert.indexOf('(') - 1)
        }}
      >
        <option value="">Insert a function…</option>
        {FORMULA_FUNCTIONS.map((f) => (
          <option key={f.name} value={f.name}>
            {f.name}: {f.help}
          </option>
        ))}
      </Select>
      <div className="space-y-1.5 rounded-md bg-canvas-subtle px-3 py-2 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-fg-subtle">Try it on</span>
          <RecordSearchPicker
            schemaName={ctx.schemaName}
            value={recordId}
            onChange={(id) => setRecordId(id ?? undefined)}
            placeholder="The latest record"
            aria-label="Record to try the formula on"
            className="w-64"
          />
        </div>
        {refused ? (
          <p role="alert" className="text-danger">
            {refused}
          </p>
        ) : data ? (
          <p
            role="status"
            data-testid="formula-preview"
            className="flex min-w-0 items-baseline gap-2"
          >
            <span className="shrink-0 text-xs text-fg-subtle">
              {data.record_id
                ? `For ${data.record_name ?? data.record_id.slice(0, 8)}`
                : 'With no record yet'}
            </span>
            {data.error ? (
              <span className="text-warning">Blank: {data.error}</span>
            ) : (
              <span className="min-w-0 font-mono text-fg">
                <FieldValue
                  value={data.value}
                  field={shownAs({
                    id: '',
                    name: '',
                    label: null,
                    required: false,
                    default: null,
                    position: null,
                    type: 'formula',
                    restrictions: { ...rules, result: data.result },
                  })}
                />
              </span>
            )}
          </p>
        ) : null}
      </div>
    </Shell>
  )
}

/** What a formula gives; empty = worked out from the formula on save. */
export function FormulaResultControl({ desc, rules, set }: ControlProps) {
  const value =
    typeof rules[desc.key] === 'string' ? (rules[desc.key] as string) : ''
  return (
    <Shell label={desc.label} help={desc.help}>
      <Select
        size="sm"
        value={value}
        aria-label={desc.label}
        onChange={(e) => set(desc.key, e.target.value || undefined)}
        className="w-56"
      >
        <option value="">Worked out from the formula</option>
        {FORMULA_RESULTS.map((r) => (
          <option key={r.value} value={r.value}>
            {r.label}
          </option>
        ))}
      </Select>
    </Shell>
  )
}

/** 0 to 10 decimal places. */
export function DecimalsControl({ desc, rules, set }: ControlProps) {
  const stored = rules[desc.key]
  return (
    <Shell label={desc.label} help={desc.help}>
      <Input
        size="sm"
        type="number"
        step="1"
        min={0}
        max={10}
        value={typeof stored === 'number' ? String(stored) : ''}
        placeholder="as worked out"
        aria-label={desc.label}
        onChange={(e) => {
          const n = parseInt(e.target.value, 10)
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
