import { useState } from 'react'
import type { SavedSummary, View } from '../../api/views'
import { useRecordSummary } from '../../hooks/useRecords'
import {
  Button,
  Chip,
  Field,
  FormError,
  IconButton,
  InfoTip,
  Input,
  Menu,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  SegmentedControl,
  Select,
  type MenuEntry,
} from '../ui'
import { BarChart3, ChevronDown, Plus, X } from '../ui/icons'
import { SummaryResult } from './SummaryResult'
import { errorMessage } from '../../lib/errors'
import { displayLabel, viewNameError } from '../../utils/naming'
import type { FilterableField } from '../../utils/hierarchy'
import type { FilterTreeWire } from '../../utils/filterTree'
import {
  fieldKey,
  groupingWords,
  savedSummaryOf,
  splitGroupKey,
} from '../../utils/summary'
import type { SummaryChoicesState } from './useSummaryChoices'

const PERIODS = ['year', 'month', 'week', 'day']
const MAX_GROUPINGS = 3

/** The records the explorer lists, summarised. The choices read as one
 * sentence ("Work out [Records] for the Sample records listed, grouped by
 * [Site] then by [Taken: by month]"), each slot a dropdown in plain words with
 * a tip; with nothing chosen it groups by a sensible field, so the screen is
 * never blank. Everything is in the address (`useSummaryChoices`), so a
 * summary is a link, and **Save analysis…** keeps it as a saved view. Clicking
 * a group lists its records. Downloading it is the explorer's Export menu. */
export function SummaryView({
  summary,
  kindLabel,
  onDrill,
  analysis,
  onSaveAnalysis,
  where,
  mayWrite,
  cannotWrite,
}: {
  /** The Summary's choices (the explorer reads them once, for its Export
   * menu too). */
  summary: SummaryChoicesState
  /** The listed kind, as the page calls it ("Sample"). */
  kindLabel: string
  /** List the records of a group: its condition, added to the filter. */
  onDrill: (where: FilterTreeWire) => void
  /** The saved view this was opened from, if any (an analysis is updated). */
  analysis: View | null
  /** Save as a new analysis (`name`) or update `analysis` (`name` null). */
  onSaveAnalysis: (name: string | null, saved: SavedSummary) => Promise<unknown>
  /** Where the Summary is: what a saved analysis remembers. */
  where: {
    collection: string | null
    within: string | null
    search: string | null
  }
  mayWrite: boolean
  /** Why saving is switched off, when it is. */
  cannotWrite?: string
}) {
  const { choices, by, byDefault, measures, usable, types, body } = summary
  const { data, isLoading, isFetching, error } = useRecordSummary(body)
  const [saving, setSaving] = useState(false)

  const measureNames = new Map(
    (types?.summary_measures ?? []).map((m) => [m.key, m]),
  )
  const byKey = new Map(usable.map((u) => [fieldKey(u.field), u]))
  const groupable = usable.filter((u) => u.type.grouping)

  function labelOf(f: FilterableField) {
    const own = displayLabel(f.name, f.label)
    return f.relation === 'self' ? own : `${f.sourceSchemaName} › ${own}`
  }

  // A grouping's first form: a date by month, anything else by each value.
  const startOf = (key: string) => {
    const u = byKey.get(key)
    return u?.type.grouping === 'bucket' && u.type.buckets.includes('month')
      ? `${key}:month`
      : key
  }

  // --- what can be worked out
  const measureItems: MenuEntry[] = []
  if (!measures.includes('count'))
    measureItems.push({
      label: measureNames.get('count')?.label ?? 'Records',
      hint: measureNames.get('count')?.help,
      onClick: () => summary.setMeasures([...measures, 'count']),
    })
  for (const { field, type } of usable) {
    const key = fieldKey(field)
    const open = type.measures.filter((m) => !measures.includes(`${m}:${key}`))
    if (open.length === 0) continue
    measureItems.push({ heading: labelOf(field) })
    for (const m of open)
      measureItems.push({
        label: measureNames.get(m)?.label ?? m,
        hint: measureNames.get(m)?.help,
        onClick: () => summary.setMeasures([...measures, `${m}:${key}`]),
      })
  }
  const measureLabel = (key: string) =>
    data?.measure_columns.find((c) => c.key === key)?.label ??
    measureNames.get(key)?.label ??
    key

  /** The fields a grouping slot offers, by the kind they belong to. */
  function fieldOptions(current: string) {
    const kinds = new Map<string, typeof groupable>()
    for (const u of groupable) {
      const key = fieldKey(u.field)
      if (key !== current && by.some((b) => splitGroupKey(b).field === key))
        continue
      const list = kinds.get(u.field.sourceSchemaName) ?? []
      list.push(u)
      kinds.set(u.field.sourceSchemaName, list)
    }
    return [...kinds.entries()].map(([kind, list]) => (
      <optgroup key={kind} label={kind}>
        {list.map((u) => (
          <option key={fieldKey(u.field)} value={fieldKey(u.field)}>
            {displayLabel(u.field.name, u.field.label)}
          </option>
        ))}
      </optgroup>
    ))
  }

  function groupSlot(index: number) {
    const key = by[index]
    const { field, how } = splitGroupKey(key)
    const u = byKey.get(field)
    const name = u ? labelOf(u.field) : field
    const unit =
      typeof u?.field.restrictions?.unit === 'string'
        ? (u.field.restrictions.unit as string)
        : null
    const replace = (next: string) =>
      summary.setBy(by.map((b, i) => (i === index ? next : b)))
    return (
      <span className="inline-flex flex-wrap items-center gap-1">
        <Select
          size="sm"
          aria-label={index === 0 ? 'Group by' : `Then by (${index + 1})`}
          value={field}
          onChange={(e) =>
            e.target.value
              ? replace(startOf(e.target.value))
              : summary.setBy(by.filter((_, i) => i !== index))
          }
        >
          {index === 0 && by.length === 1 && (
            <option value="">nothing (one total)</option>
          )}
          {!byKey.has(field) && <option value={field}>{field}</option>}
          {fieldOptions(field)}
        </Select>
        {u?.type.grouping === 'bucket' && (
          <Select
            size="sm"
            aria-label={`How to group ${name}`}
            value={how}
            onChange={(e) =>
              replace(e.target.value ? `${field}:${e.target.value}` : field)
            }
          >
            <option value="">each value</option>
            {u.type.buckets
              .filter((b) => PERIODS.includes(b))
              .map((b) => (
                <option key={b} value={b}>
                  {groupingWords(b, u.type)}
                </option>
              ))}
          </Select>
        )}
        {u?.type.grouping === 'bin' && (
          <span className="inline-flex items-center gap-1 text-fg-muted">
            <span>{how ? 'in ranges of' : 'each value, or ranges of'}</span>
            <Field label={`Range width for ${name}`} hideLabel>
              <Input
                key={key}
                size="sm"
                type="number"
                min={0}
                step="any"
                className="w-20"
                placeholder="width"
                defaultValue={how}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') e.currentTarget.blur()
                }}
                onBlur={(e) => {
                  const w = Number(e.target.value)
                  const next = e.target.value && w > 0 ? `${field}:${w}` : field
                  if (next !== key) replace(next)
                }}
              />
            </Field>
            {unit && <span>{unit}</span>}
          </span>
        )}
        {u?.type.grouping === 'each' && (
          <span className="text-fg-muted">({groupingWords(how, u.type)})</span>
        )}
        {index > 0 && (
          <IconButton
            icon={X}
            size="sm"
            aria-label={`Stop grouping by ${name}`}
            onClick={() => summary.setBy(by.filter((_, i) => i !== index))}
          />
        )}
      </span>
    )
  }

  const nextField = groupable
    .map((u) => fieldKey(u.field))
    .find((k) => !by.some((b) => splitGroupKey(b).field === k))

  if (!body)
    return (
      <p className="text-sm text-fg-muted">
        Choose a kind of record to summarise.
      </p>
    )

  return (
    <div className="space-y-3">
      <div
        className="flex flex-wrap items-center gap-x-2 gap-y-2 rounded-md border border-border bg-canvas-subtle p-3 text-sm"
        role="group"
        aria-label="What the summary works out"
      >
        <span className="inline-flex items-center gap-1 font-medium">
          Work out
          <InfoTip label="About what is worked out">
            What each row counts or measures: how many records there are, or for
            a field, how many have it filled, its smallest, largest, average or
            total. Add as many as you like.
          </InfoTip>
        </span>
        {measures.map((key) => (
          <Chip
            key={key}
            onRemove={
              measures.length > 1
                ? () => summary.setMeasures(measures.filter((m) => m !== key))
                : undefined
            }
            removeLabel={`Stop working out ${measureLabel(key)}`}
          >
            {measureLabel(key)}
          </Chip>
        ))}
        {measureItems.length > 0 && (
          <Menu
            align="left"
            wide
            items={measureItems}
            trigger={({ open, toggle }) => (
              <Button
                size="sm"
                variant="ghost"
                aria-haspopup="menu"
                aria-expanded={open}
                onClick={toggle}
              >
                <Plus size={14} /> Add… <ChevronDown size={14} />
              </Button>
            )}
          />
        )}
        <span>
          of the <span className="font-medium">{kindLabel}</span> records
          listed,
        </span>
        <span className="inline-flex items-center gap-1 font-medium">
          grouped by
          <InfoTip label="About grouping">
            Grouping puts records with the same value in one row: grouped by
            Site, each site gets a row with its own count. A date can be grouped
            by year or month, a number into ranges (every 5 m, say). Add a
            second grouping to split each row again: Site, then Year. With
            nothing to group by you get one total.
          </InfoTip>
        </span>
        {by.length === 0 ? (
          <Select
            size="sm"
            aria-label="Group by"
            value=""
            onChange={(e) =>
              e.target.value && summary.setBy([startOf(e.target.value)])
            }
          >
            <option value="">nothing (one total)</option>
            {fieldOptions('')}
          </Select>
        ) : (
          by.map((key, i) => (
            <span key={key} className="inline-flex items-center gap-1">
              {i > 0 && <span className="font-medium">then by</span>}
              {groupSlot(i)}
            </span>
          ))
        )}
        {by.length > 0 && by.length < MAX_GROUPINGS && nextField && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => summary.setBy([...by, startOf(nextField)])}
          >
            <Plus size={14} /> then by…
          </Button>
        )}
        {byDefault && by.length > 0 && (
          <span className="text-xs text-fg-muted">
            (a start: group by anything you like)
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <SegmentedControl
          size="sm"
          label="Show the summary as"
          value={choices.show}
          onChange={(v) => summary.set({ view: v === 'chart' ? 'chart' : '' })}
          options={[
            { value: 'table', label: 'Table' },
            { value: 'chart', label: 'Chart' },
          ]}
        />
        <InfoTip label="About summaries">
          Worked out over every record the list shows, with its filters and
          search. A date known only to the year keeps a group of its own when
          grouped by month. A list (tags, links) puts a record in a group for
          each item, so groups can add up to more than the total. Click a group
          to list its records. To download it, use Export.
        </InfoTip>
        <div className="ml-auto flex items-center gap-2">
          {analysis?.summary && (
            <span className="inline-flex items-center gap-1 text-sm text-fg-muted">
              <BarChart3 size={14} aria-hidden="true" />
              Analysis “{analysis.name}”
            </span>
          )}
          <Button
            size="sm"
            onClick={() => setSaving(true)}
            disabled={!mayWrite}
            title={mayWrite ? undefined : cannotWrite}
          >
            Save analysis…
          </Button>
        </div>
      </div>

      <SummaryResult
        data={data}
        isLoading={isLoading}
        isFetching={isFetching}
        error={error}
        show={choices.show}
        sort={choices.sort}
        onSort={(column) =>
          summary.set({
            sort:
              choices.sort?.column !== column
                ? `${column}:asc`
                : choices.sort.direction === 'asc'
                  ? `${column}:desc`
                  : '',
          })
        }
        chartMeasure={choices.y}
        onChartMeasure={(y) => summary.set({ y })}
        onDrill={onDrill}
      />

      {saving && (
        <SaveAnalysisDialog
          analysis={analysis?.summary ? analysis : null}
          onClose={() => setSaving(false)}
          onSave={(name) =>
            onSaveAnalysis(name, savedSummaryOf(choices, by, where)).then(() =>
              setSaving(false),
            )
          }
        />
      )}
    </div>
  )
}

/** Name a saved analysis: a new one, or (opened from one) update it. */
function SaveAnalysisDialog({
  analysis,
  onSave,
  onClose,
}: {
  analysis: View | null
  /** `name`: save as new; null: update `analysis`. */
  onSave: (name: string | null) => Promise<unknown>
  onClose: () => void
}) {
  const [name, setName] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const invalid = viewNameError(name.trim())
  const run = (n: string | null) => {
    setPending(true)
    setError(null)
    onSave(n).catch((e) => {
      setError(e)
      setPending(false)
    })
  }
  return (
    <Modal onClose={onClose} size="sm" dismissible={!pending}>
      <ModalHeader onClose={onClose}>Save analysis</ModalHeader>
      <ModalBody className="space-y-3">
        <p className="text-sm text-fg-muted">
          Keeps this summary with the list's filters and search, for everyone in
          the project. It is listed with the saved lists, can be pinned, and can
          be put on the Analytics page.
        </p>
        {analysis && (
          <p className="text-sm">
            Opened from <span className="font-medium">“{analysis.name}”</span>:
            update it, or save these choices as a new analysis.
          </p>
        )}
        <Field
          label={analysis ? 'Name for a new analysis' : 'Name'}
          error={name ? (invalid ?? undefined) : undefined}
        >
          <Input
            autoFocus
            value={name}
            placeholder="Samples by site and month"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !invalid) run(name.trim())
            }}
          />
        </Field>
        {error != null && <FormError message={errorMessage(error)} />}
      </ModalBody>
      <ModalFooter>
        <Button size="sm" onClick={onClose} disabled={pending}>
          Cancel
        </Button>
        {analysis && (
          <Button size="sm" disabled={pending} onClick={() => run(null)}>
            Update “{analysis.name}”
          </Button>
        )}
        <Button
          size="sm"
          variant="primary"
          disabled={!!invalid || pending}
          onClick={() => run(name.trim())}
        >
          {pending ? 'Saving…' : analysis ? 'Save as new' : 'Save analysis'}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
