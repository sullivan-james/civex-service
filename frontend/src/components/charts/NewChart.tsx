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
  PERIOD_CHOICES,
  SHOWS,
  barFields,
  barHow,
  buildChart,
  chartTitle,
  kindsBeneath,
  mapChart,
  measureFields,
  plural,
  recommendedCharts,
  type Usable,
} from '../../utils/charts'
import { mapFields } from '../explorer/MapView'
import { ChartView } from './ChartView'

/** Building a chart, at full width: the choices on the left, the chart they
 * make on the right, drawn live over the records it will count. Two choices
 * make bars: **One bar for each** (a field; a date's period, a number's
 * steps) and **Each bar shows** (how many, or a number worked out). **A
 * map** needs none. Ready-made charts for the kind fill the choices in with
 * one click. Nothing is added until **Add chart**. */
export function NewChart({
  listed,
  schemas,
  usable,
  kind,
  records,
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
  onAdd: (chart: Chart) => void
  onCancel: () => void
}) {
  const bars = barFields(usable)
  const fields = usable.map((u) => u.field)
  const geo = mapFields(fields)
  const below = kindsBeneath(listed, schemas)
  const recommended = recommendedCharts(usable)
  const [what, setWhat] = useState<'bars' | 'map'>('bars')
  const [by, setBy] = useState(bars[0]?.value ?? '')
  const [period, setPeriod] = useState('month')
  const [steps, setSteps] = useState('10')
  const [show, setShow] = useState('count')
  const [of, setOf] = useState('')
  const [title, setTitle] = useState('')

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
  const valid =
    what === 'map'
      ? geo.length > 0
      : !!by && (how !== 'steps' || Number(steps) > 0)
  const drawn: Chart =
    what === 'map' && geo[0]
      ? mapChart(geo[0])
      : buildChart({
          by,
          how: how === 'period' ? period : how === 'steps' ? steps : '',
          show,
          of: ofValue,
        })
  const named = chartTitle(drawn, usable, kind, schemas)
  const chart: Chart = { ...drawn, title: title.trim() || null }
  // The preview follows the choices, a moment behind while typing.
  const previewed = useDeferredValue(
    JSON.stringify({ ...drawn, id: 'preview' }),
  )

  /** Fill the choices in from a ready-made chart. */
  function use(c: Chart) {
    const [field, cut = ''] = (c.group_by[0] ?? '').split(':')
    setWhat('bars')
    setBy(field)
    if (cut) setPeriod(cut)
    setShow('count')
  }

  return (
    <Card
      title="New chart"
      selected
      action={
        <div className="flex gap-2">
          <Button size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            size="sm"
            variant="primary"
            disabled={!valid}
            onClick={() => onAdd(chart)}
          >
            Add chart
          </Button>
        </div>
      }
    >
      <div className="grid gap-6 lg:grid-cols-[20rem_1fr]">
        <div className="space-y-4">
          {recommended.length > 0 && (
            <div className="space-y-2">
              <Subheading>Quick picks</Subheading>
              <div className="flex flex-wrap gap-2">
                {recommended.map((c) => (
                  <Chip
                    key={c.group_by[0]}
                    selected={
                      what === 'bars' &&
                      show === 'count' &&
                      drawn.group_by[0] === c.group_by[0]
                    }
                    onClick={() => use(c)}
                  >
                    {chartTitle(c, usable, kind, schemas)}
                  </Chip>
                ))}
              </div>
            </div>
          )}
          {geo.length > 0 && (
            <SegmentedControl
              size="sm"
              label="Kind of chart"
              value={what}
              onChange={setWhat}
              options={[
                { value: 'bars', label: 'Bars' },
                { value: 'map', label: 'A map' },
              ]}
            />
          )}
          {what === 'bars' && (
            <>
              <div className="space-y-2">
                <Field label="One bar for each">
                  <Select value={by} onChange={(e) => setBy(e.target.value)}>
                    {bars.map((b) => (
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
              <div className="space-y-2">
                <Field label="Each bar shows">
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
            </>
          )}
          <Field label="Title">
            <Input
              value={title}
              placeholder={named}
              maxLength={200}
              onChange={(e) => setTitle(e.target.value)}
            />
          </Field>
        </div>
        <section aria-label="Preview" className="min-w-0 space-y-2">
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
