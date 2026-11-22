import { useMemo, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router'
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  IconButton,
  Input,
  Field,
  Menu,
  Page,
  Select,
  SegmentedControl,
  Skeleton,
  SortableList,
  type MenuEntry,
} from '../components/ui'
import { Plus, Trash2 } from '../components/ui/icons'
import {
  AnalyticsFilterBar,
  JobSuccessRateWidget,
  PluginFailuresWidget,
  DurationDistributionWidget,
  TriggerBreakdownWidget,
  AuditActivityWidget,
  AuditEntityBreakdownWidget,
  AiTokenUsageWidget,
  RecordGrowthWidget,
  RecordCountsWidget,
  StorageUsageWidget,
  SchemaLintWidget,
} from '../components/analytics'
import { WidgetCard } from '../components/analytics/WidgetCard'
import { ChartView } from '../components/charts/ChartView'
import { OpenChart } from '../components/charts/ChartBoard'
import { useAnalyticsFilters } from '../hooks/useAnalyticsFilters'
import type { AnalyticsFiltersState } from '../utils/analyticsFilters'
import { useWorkflows } from '../hooks/useWorkflows'
import { usePlugins } from '../hooks/usePlugins'
import { useCollections } from '../hooks/useCollections'
import { useSchemas } from '../hooks/useSchemas'
import { useFieldTypes } from '../hooks/useFieldTypes'
import {
  storedCard,
  useDashboard,
  useSaveDashboard,
} from '../hooks/useDashboard'
import { usePermissions } from '../hooks/useMe'
import type { DashboardCard, DashboardCardShown } from '../api/dashboard'
import type { RecordSelectionBody } from '../api/records'
import type { Schema } from '../api/schemas'
import { OPEN_CHART_PARAM, chartTitle, type Usable } from '../utils/charts'
import { filterableFields } from '../utils/hierarchy'
import { displayLabel } from '../utils/naming'
import { summaryFields } from '../utils/summary'
import { errorMessage } from '../lib/errors'

const STATUS_OPTIONS = [
  { value: 'pending', label: 'Pending' },
  { value: 'running', label: 'Running' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
]

const TRIGGER_OPTIONS = [
  { value: 'record_created', label: 'Record created' },
  { value: 'record_updated', label: 'Record updated' },
  { value: 'manual', label: 'Manual' },
]

const ENTITY_TYPE_OPTIONS = [
  { value: 'record', label: 'Record' },
  { value: 'schema', label: 'Schema' },
  { value: 'field', label: 'Field' },
  { value: 'dataset', label: 'Dataset' },
]

const ACTION_OPTIONS = [
  { value: 'create', label: 'Create' },
  { value: 'update', label: 'Update' },
  { value: 'delete', label: 'Delete' },
  { value: 'purge', label: 'Purge' },
]

/** The built-in widgets by the key a card names (civex/domain/dashboard.py
 * `WIDGETS`): each draws itself over the page's filter bar. */
const WIDGETS: Record<string, (f: AnalyticsFiltersState) => ReactNode> = {
  record_growth: (f) => <RecordGrowthWidget filters={f} />,
  record_counts: (f) => <RecordCountsWidget filters={f} />,
  storage: () => <StorageUsageWidget />,
  schema_lint: () => <SchemaLintWidget />,
  run_success: (f) => <JobSuccessRateWidget filters={f} />,
  plugin_failures: (f) => <PluginFailuresWidget filters={f} />,
  durations: (f) => <DurationDistributionWidget filters={f} />,
  triggers: (f) => <TriggerBreakdownWidget filters={f} />,
  activity: (f) => <AuditActivityWidget filters={f} />,
  activity_kinds: (f) => <AuditEntityBreakdownWidget filters={f} />,
  ai_tokens: (f) => <AiTokenUsageWidget filters={f} />,
}

/** Address name: the collection every chart card is narrowed to. */
const FOR_PARAM = 'for'

/** The project's Analytics page: one shared list of cards, each a chart
 * with the records it counts (the one chart definition and renderer,
 * `ChartView`) or a built-in widget, small (half the page) or wide. A chart
 * is put here from a list of records (**Add to Analytics page**). **For**
 * narrows every chart to one collection; a card is enlarged (`?chart=`).
 * Anyone who may change records somewhere may edit the page (**Edit page**:
 * reorder, resize, retitle, remove, add a built-in chart, then **Done**,
 * saved as one change); it syncs and is in Activity. The filter bar governs
 * the built-in widgets. */
export default function AnalyticsPage() {
  const { filters, setFilters, resetFilters } = useAnalyticsFilters()
  const { data: workflows } = useWorkflows()
  const { data: plugins } = usePlugins()
  const { data: collections } = useCollections()
  const { data: schemas } = useSchemas()
  const types = useFieldTypes()
  const page = useDashboard()
  const save = useSaveDashboard()
  const { canSomewhere, why } = usePermissions()
  const mayEdit = canSomewhere('views')
  const [sp, setSp] = useSearchParams()
  const editing = sp.get('edit') === '1' && mayEdit
  const [draft, setDraft] = useState<DashboardCardShown[] | null>(null)

  const shown = (editing ? draft : null) ?? page.data?.cards
  const cards = useMemo(() => shown ?? [], [shown])
  const names = page.data?.widgets ?? {}
  const only = sp.get(FOR_PARAM)
  const setParam = (key: string, value: string | null, replace = true) =>
    setSp(
      (prev) => {
        const out = new URLSearchParams(prev)
        if (value) out.set(key, value)
        else out.delete(key)
        return out
      },
      { replace },
    )

  // A chart card as it is drawn: its kind's fields, its title, its records.
  const drawn = useMemo(() => {
    const all = schemas ?? []
    return new Map(
      cards.flatMap((c) => {
        const listed = all.find((s) => s.name === c.schema_name)
        if (!c.chart || !c.records || !listed) return []
        const usable = summaryFields(
          filterableFields(listed, all),
          types?.types ?? [],
        )
        const chart = { ...c.chart, id: c.id }
        const kind = displayLabel(listed.name, listed.label)
        const records: RecordSelectionBody = {
          collection: only ?? c.collection_name ?? null,
          schema_name: listed.name,
          within: c.records.within ?? null,
          search: c.records.search ?? null,
          filter: c.records.filter ?? null,
        }
        const title = c.title ?? chartTitle(chart, usable, kind, all)
        return [
          [c.id, { chart, usable, kind, records, title, listed }] as const,
        ]
      }),
    )
  }, [cards, schemas, types, only])

  const setEditing = (on: boolean) => {
    setDraft(on ? (page.data?.cards ?? []) : null)
    setParam('edit', on ? '1' : null)
  }
  const done = () => {
    const before = JSON.stringify((page.data?.cards ?? []).map(storedCard))
    const after = cards.map(storedCard)
    if (JSON.stringify(after) === before) return setEditing(false)
    save.mutate(after, { onSuccess: () => setEditing(false) })
  }
  const change = (id: string, patch: Partial<DashboardCard>) =>
    setDraft(cards.map((c) => (c.id === id ? { ...c, ...patch } : c)))

  const hasWidgets = cards.some((c) => c.kind === 'widget')
  const hasCharts = cards.some((c) => c.kind === 'chart')
  const opened = drawn.get(sp.get(OPEN_CHART_PARAM) ?? '')
  const cardName = (c: DashboardCardShown) =>
    c.title ??
    drawn.get(c.id)?.title ??
    (c.kind === 'chart' ? 'Chart' : (names[c.widget ?? ''] ?? c.widget ?? ''))

  return (
    <Page
      title="Analytics"
      action={
        editing ? (
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={() => setEditing(false)}
              disabled={save.isPending}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={done}
              disabled={save.isPending}
            >
              {save.isPending ? 'Saving…' : 'Done'}
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            {hasCharts && (
              <Field label="For" hideLabel>
                <Select
                  size="sm"
                  aria-label="For"
                  value={only ?? ''}
                  onChange={(e) => setParam(FOR_PARAM, e.target.value || null)}
                >
                  <option value="">For: each chart's own records</option>
                  {(collections ?? []).map((c) => (
                    <option key={c.id} value={c.name}>
                      For: {c.name}
                    </option>
                  ))}
                </Select>
              </Field>
            )}
            <Button
              size="sm"
              onClick={() => setEditing(true)}
              disabled={!mayEdit || !page.data}
              title={mayEdit ? undefined : why('views')}
            >
              Edit page
            </Button>
          </div>
        )
      }
    >
      {hasWidgets && !editing && (
        <AnalyticsFilterBar
          filters={filters}
          onChange={setFilters}
          onReset={resetFilters}
          datasetOptions={(collections ?? []).map((c) => ({
            value: c.name,
            label: c.name,
          }))}
          schemaOptions={(schemas ?? []).map((s) => ({
            value: s.name,
            label: s.name,
          }))}
          workflowOptions={(workflows ?? []).map((w) => ({
            value: w.name,
            label: w.name,
          }))}
          pluginOptions={(plugins ?? []).map((p) => ({
            value: p.id,
            label: p.name,
          }))}
          statusOptions={STATUS_OPTIONS}
          triggerOptions={TRIGGER_OPTIONS}
          entityTypeOptions={ENTITY_TYPE_OPTIONS}
          actionOptions={ACTION_OPTIONS}
        />
      )}

      {opened && !editing && (
        <OpenChart
          chart={opened.chart}
          title={opened.title}
          records={opened.records}
          usable={opened.usable}
          onClose={() => setParam(OPEN_CHART_PARAM, null, false)}
        />
      )}

      {page.error ? (
        <ErrorState message={errorMessage(page.error)} />
      ) : !page.data ? (
        <Skeleton className="h-64" />
      ) : editing ? (
        <EditCards
          cards={cards}
          names={names}
          cardName={cardName}
          onChange={setDraft}
          onCard={change}
          error={save.error}
        />
      ) : cards.length === 0 ? (
        <EmptyState title="Nothing here yet" />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {cards.map((c) => (
            <div
              key={c.id}
              className={c.size === 'wide' ? 'lg:col-span-2' : undefined}
            >
              {c.kind === 'chart' ? (
                <ChartCard
                  card={c}
                  title={cardName(c)}
                  drawn={drawn.get(c.id)}
                  onOpen={() => setParam(OPEN_CHART_PARAM, c.id, false)}
                />
              ) : (
                <>
                  {c.title && (
                    <h2 className="mb-2 text-sm font-semibold text-fg">
                      {c.title}
                    </h2>
                  )}
                  {WIDGETS[c.widget ?? '']?.(filters) ?? (
                    <WidgetCard title={c.widget ?? 'Widget'}>
                      <p className="text-sm text-fg-muted">Unknown chart</p>
                    </WidgetCard>
                  )}
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </Page>
  )
}

/** A chart card: the chart over its records, a way to open it large and a
 * way to the records themselves. */
function ChartCard({
  card,
  title,
  drawn,
  onOpen,
}: {
  card: DashboardCardShown
  title: string
  drawn?: {
    chart: Parameters<typeof ChartView>[0]['chart']
    usable: Usable[]
    records: RecordSelectionBody
    listed: Schema
  }
  onOpen: () => void
}) {
  if (!drawn || card.problem)
    return (
      <Card title={title}>
        <p className="text-sm text-fg-muted">
          {card.problem ?? 'That kind of record is gone'}
        </p>
      </Card>
    )
  const where = drawn.records.collection
    ? `/collections/${encodeURIComponent(drawn.records.collection)}`
    : '/collections?tab=records'
  const query = new URLSearchParams({ schema: drawn.listed.name })
  if (drawn.records.within) query.set('within', drawn.records.within)
  if (drawn.records.search) query.set('q', drawn.records.search)
  if (drawn.records.filter)
    query.set('filter', JSON.stringify(drawn.records.filter))
  return (
    <Card
      title={title}
      action={
        <div className="flex items-center gap-1">
          <Button
            size="sm"
            variant="ghost"
            to={`${where}${where.includes('?') ? '&' : '?'}${query}`}
          >
            Records
          </Button>
          <Button size="sm" variant="ghost" onClick={onOpen}>
            Numbers
          </Button>
        </div>
      }
    >
      <ChartView
        chart={drawn.chart}
        records={drawn.records}
        fields={drawn.usable.map((u) => u.field)}
      />
    </Card>
  )
}

/** The page being edited: the cards in order (drag by the grip, or the
 * arrows), each with its size, its own title and a way off the page, and
 * **Add a card** for the built-in charts not on it (a chart of records is
 * added from a list of them). */
function EditCards({
  cards,
  names,
  cardName,
  onChange,
  onCard,
  error,
}: {
  cards: DashboardCardShown[]
  names: Record<string, string>
  cardName: (c: DashboardCardShown) => string
  onChange: (next: DashboardCardShown[]) => void
  onCard: (id: string, patch: Partial<DashboardCard>) => void
  error: unknown
}) {
  const onPage = new Set(cards.map((c) => c.widget))
  const newId = (base: string) => {
    let id = base
    for (let n = 2; cards.some((c) => c.id === id); n++) id = `${base}-${n}`
    return id
  }
  const items: MenuEntry[] = Object.entries(names)
    .filter(([k]) => !onPage.has(k))
    .map(([key, name]) => ({
      label: name,
      onClick: () =>
        onChange([
          ...cards,
          {
            id: newId(`widget-${key}`),
            kind: 'widget',
            size: key === 'ai_tokens' ? 'wide' : 'small',
            widget: key,
          },
        ]),
    }))

  return (
    <div className="space-y-3">
      {error != null && <ErrorState message={errorMessage(error)} />}
      <SortableList
        label="Cards on the page"
        items={cards}
        getKey={(c) => c.id}
        getLabel={cardName}
        onReorder={(next) => onChange(next)}
        moveButtons="always"
        renderItem={(c) => (
          <div className="flex flex-wrap items-center gap-3 py-1">
            <span className="min-w-0 flex-1 truncate text-sm font-medium">
              {cardName(c)}
            </span>
            <Field label={`Title for ${cardName(c)}`} hideLabel>
              <Input
                size="sm"
                className="w-48"
                placeholder="Title"
                value={c.title ?? ''}
                maxLength={200}
                onChange={(e) =>
                  onCard(c.id, { title: e.target.value || null })
                }
              />
            </Field>
            <SegmentedControl
              size="sm"
              label={`Size of ${cardName(c)}`}
              value={c.size}
              onChange={(size) => onCard(c.id, { size })}
              options={[
                { value: 'small', label: 'Half' },
                { value: 'wide', label: 'Full width' },
              ]}
            />
            <IconButton
              icon={Trash2}
              size="sm"
              aria-label={`Take ${cardName(c)} off the page`}
              onClick={() => onChange(cards.filter((o) => o.id !== c.id))}
            />
          </div>
        )}
      />
      {items.length > 0 && (
        <Menu
          align="left"
          wide
          items={items}
          trigger={({ open, toggle }) => (
            <Button
              size="sm"
              aria-haspopup="menu"
              aria-expanded={open}
              onClick={toggle}
            >
              <Plus size={14} /> Add a card
            </Button>
          )}
        />
      )}
    </div>
  )
}
