import { useState } from 'react'
import type { Chart, Schema } from '../../api/schemas'
import { Button, Card, Field, Input, SegmentedControl, Select } from '../ui'
import {
  PERIOD_CHOICES,
  SHOWS,
  barFields,
  barHow,
  buildChart,
  chartTitle,
  kindsBeneath,
  mapChart,
  plural,
  measureFields,
  type Usable,
} from '../../utils/charts'
import { mapFields } from '../explorer/MapView'

/** The "New chart" panel: **One bar for each** (a field; a date's period, a
 * number's steps) and **Each bar shows** (how many, or a number worked out),
 * or **A map** where the kind has a location. The title it will get is shown
 * before it is added. */
export function NewChart({
  listed,
  schemas,
  usable,
  kind,
  onAdd,
  onCancel,
}: {
  listed: Schema
  schemas: Schema[]
  usable: Usable[]
  /** The kind's display name ("Sample"). */
  kind: string
  onAdd: (chart: Chart) => void
  onCancel: () => void
}) {
  const bars = barFields(usable)
  const geo = mapFields(usable.map((u) => u.field))
  const below = kindsBeneath(listed, schemas)
  const [what, setWhat] = useState<'bars' | 'map'>('bars')
  const [by, setBy] = useState(bars[0]?.value ?? '')
  const [period, setPeriod] = useState('month')
  const [steps, setSteps] = useState('10')
  const [show, setShow] = useState('count')
  const [of, setOf] = useState('')

  const how = barHow(usable, by)
  const shows = SHOWS.filter((s) =>
    s.of === 'field'
      ? measureFields(usable, s.value).length > 0
      : s.of === 'kind'
        ? below.length > 0
        : true,
  )
  const ofChoices =
    SHOWS.find((s) => s.value === show)?.of === 'kind'
      ? below
      : measureFields(usable, show)
  const ofValue = ofChoices.some((c) => c.value === of)
    ? of
    : (ofChoices[0]?.value ?? '')
  const chart =
    what === 'map' && geo[0]
      ? mapChart(geo[0])
      : buildChart({
          by,
          how: how === 'period' ? period : how === 'steps' ? steps : '',
          show,
          of: ofValue,
        })
  const valid =
    what === 'map' || (!!by && (how !== 'steps' || Number(steps) > 0))

  return (
    <Card title="New chart" selected>
      <div className="space-y-3">
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
              <Field label="Dates" hideLabel>
                <Select
                  aria-label="Dates"
                  value={period}
                  onChange={(e) => setPeriod(e.target.value)}
                >
                  {PERIOD_CHOICES.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                    </option>
                  ))}
                </Select>
              </Field>
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
            <Field label="Each bar shows">
              <Select value={show} onChange={(e) => setShow(e.target.value)}>
                {shows.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.value === 'count' ? `How many ${plural(kind)}` : s.label}
                  </option>
                ))}
              </Select>
            </Field>
            {show !== 'count' && (
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
          </>
        )}
        <p className="text-sm font-medium text-fg" aria-live="polite">
          {chartTitle(chart, usable, kind, schemas)}
        </p>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="primary"
            disabled={!valid}
            onClick={() => onAdd(chart)}
          >
            Add chart
          </Button>
          <Button size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </div>
    </Card>
  )
}
