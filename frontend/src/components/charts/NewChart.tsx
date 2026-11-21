import { useDeferredValue, useState } from 'react'
import type { RecordSelectionBody } from '../../api/records'
import type { Chart, Schema } from '../../api/schemas'
import {
  Button,
  Card,
  Chip,
  Field,
  Input,
  SegmentedControl,
  Select,
  Subheading,
} from '../ui'
import {
  CHART_TYPES,
  PERIOD_CHOICES,
  SHOWS,
  barFields,
  barHow,
  buildChart,
  chartPick,
  chartTitle,
  chartTypes,
  kindsBeneath,
  measureFields,
  plural,
  recommendedCharts,
  type ChartType,
  type Usable,
} from '../../utils/charts'
import { ChartView } from './ChartView'

/** Building a chart, at full width: the choices on the left, the chart they
 * make on the right, drawn live over the records it will count. First
 * **What**: what to **Show** (how many, or a number worked out) **For each**
 * value of a field (a date's period, a number's steps; a location places the
 * records). Then **How**: the ways that can be drawn (bars, a line, a pie, a
 * table; a map for a location), the usual one first. Ready-made charts for
 * the kind fill the choices in with one click. Nothing is added until **Add
 * chart**. With `initial` it changes that chart instead (**Save**). */
export function NewChart({
  listed,
  schemas,
  usable,
  kind,
  records,
  initial,
  onAdd,
  onCancel,
}: {
  listed: Schema
  schemas: Schema[]
  usable: Usable[]
  /** The kind's display name ("Sample"). */
  kind: string
  /** The records the preview counts: the ones the chart will be beside. */
  records: RecordSelectionBody
  /** A chart to change (its id, size and place are kept); none: a new one. */
  initial?: Chart
  onAdd: (chart: Chart) => void
  onCancel: () => void
}) {
  const from = initial ? chartPick(initial) : null
  const each = barFields(usable)
  const fields = usable.map((u) => u.field)
  const below = kindsBeneath(listed, schemas)
  const recommended = recommendedCharts(usable)
  const [by, setBy] = useState(from?.by || (each[0]?.value ?? ''))
  const startsAs = barHow(usable, from?.by ?? '')
  const [period, setPeriod] = useState(
    (startsAs === 'period' && from?.how) || 'month',
  )
  const [steps, setSteps] = useState(
    (startsAs === 'steps' && from?.how) || '10',
  )
  const [show, setShow] = useState(from?.show ?? 'count')
  const [of, setOf] = useState(from?.of ?? '')
  const [picked, setPicked] = useState<ChartType | null>(from?.type ?? null)
  const [title, setTitle] = useState(initial?.title ?? '')

  const how = barHow(usable, by)
  const shows = SHOWS.filter((s) =>
    s.of === 'field'
      ? measureFields(usable, s.value).length > 0
      : s.of === 'kind'
        ? below.length > 0
        : true,
  )
  const needs = SHOWS.find((s) => s.value === show)?.of ?? null
  const ofChoices = needs === 'kind' ? below : measureFields(usable, show)
  const ofValue = ofChoices.some((c) => c.value === of)
    ? of
    : (ofChoices[0]?.value ?? '')
  // How it can be drawn follows from what was chosen; the usual way unless
  // another that still fits was picked.
  const types = chartTypes(usable, by, show)
  const type = picked && types.includes(picked) ? picked : types[0]
  const valid = !!by && (how !== 'steps' || Number(steps) > 0)
  const drawn = buildChart({
    by,
    how: how === 'period' ? period : how === 'steps' ? steps : '',
    show,
    of: ofValue,
    type,
  })
  const named = chartTitle(drawn, usable, kind, schemas)
  // Changed, a chart keeps its id (so its place) and its size.
  const chart: Chart = {
    ...drawn,
    id: initial?.id ?? drawn.id,
    size: initial?.size,
    title: title.trim() || null,
  }
  // The preview follows the choices, a moment behind while typing.
  const previewed = useDeferredValue(
    JSON.stringify({ ...drawn, id: 'preview' }),
  )

  /** Fill the choices in from a ready-made chart. */
  function use(c: Chart) {
    const pick = chartPick(c)
    setBy(pick.by)
    if (pick.how) setPeriod(pick.how)
    setShow('count')
    setPicked(null)
  }

  return (
    <Card title={initial ? 'Edit chart' : 'New chart'} selected>
      <div className="grid gap-8 lg:grid-cols-[22rem_1fr]">
        <div className="space-y-5">
          {!initial && recommended.length > 0 && (
            <div className="space-y-2">
              <Subheading>Quick picks</Subheading>
              <div className="flex flex-wrap gap-2">
                {recommended.map((c) => (
                  <Chip
                    key={c.group_by[0]}
                    selected={
                      show === 'count' && drawn.group_by[0] === c.group_by[0]
                    }
                    onClick={() => use(c)}
                  >
                    {chartTitle(c, usable, kind, schemas)}
                  </Chip>
                ))}
              </div>
            </div>
          )}
          <section aria-label="What" className="space-y-3">
            <Subheading>What</Subheading>
            {type !== 'map' && (
              <div className="space-y-2">
                <Field label="Show">
                  <Select
                    value={show}
                    onChange={(e) => setShow(e.target.value)}
                  >
                    {shows.map((s) => (
                      <option key={s.value} value={s.value}>
                        {s.value === 'count'
                          ? `How many ${plural(kind)}`
                          : s.label}
                      </option>
                    ))}
                  </Select>
                </Field>
                {needs && (
                  <Field label="Of" hideLabel>
                    <Select
                      aria-label="Of"
                      value={ofValue}
                      onChange={(e) => setOf(e.target.value)}
                    >
                      {ofChoices.map((c) => (
                        <option key={c.value} value={c.value}>
                          {c.label}
                        </option>
                      ))}
                    </Select>
                  </Field>
                )}
              </div>
            )}
            <div className="space-y-2">
              <Field label="For each">
                <Select value={by} onChange={(e) => setBy(e.target.value)}>
                  {each.map((b) => (
                    <option key={b.value} value={b.value}>
                      {b.label}
                    </option>
                  ))}
                </Select>
              </Field>
              {how === 'period' && (
                <SegmentedControl
                  size="sm"
                  label="Dates"
                  value={period}
                  onChange={setPeriod}
                  options={PERIOD_CHOICES.map((p) => ({
                    value: p.value,
                    label: p.label,
                  }))}
                />
              )}
              {how === 'steps' && (
                <Field label="In steps of">
                  <Input
                    type="number"
                    min={0}
                    value={steps}
                    onChange={(e) => setSteps(e.target.value)}
                  />
                </Field>
              )}
            </div>
          </section>
          <section aria-label="How" className="space-y-3">
            <Subheading>How</Subheading>
            <SegmentedControl
              size="sm"
              label="Drawn as"
              value={type}
              onChange={setPicked}
              options={types.map((t) => ({
                value: t,
                label: CHART_TYPES[t],
              }))}
            />
            <Field label="Title">
              <Input
                value={title}
                placeholder={named}
                maxLength={200}
                onChange={(e) => setTitle(e.target.value)}
              />
            </Field>
          </section>
          <div className="flex gap-2 border-t border-border pt-4">
            <Button
              variant="primary"
              disabled={!valid}
              onClick={() => onAdd(chart)}
            >
              {initial ? 'Save' : 'Add chart'}
            </Button>
            <Button variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
          </div>
        </div>
        <section
          aria-label="Preview"
          className="min-w-0 space-y-3 rounded-md border border-border bg-canvas-subtle p-4"
        >
          <Subheading as="h3">{chart.title ?? named}</Subheading>
          {valid && (
            <ChartView
              chart={JSON.parse(previewed) as Chart}
              records={records}
              fields={fields}
              large
              download={false}
            />
          )}
        </section>
      </div>
    </Card>
  )
}
