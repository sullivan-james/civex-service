import { useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router'
import {
  Button,
  EmptyState,
  ErrorState,
  IconButton,
  Input,
  Field,
  Menu,
  Page,
  SegmentedControl,
  Skeleton,
  SortableList,
  type MenuEntry,
} from '../components/ui'
import { BarChart3, Plus, Trash2 } from '../components/ui/icons'
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
import { SummaryResult } from '../components/explorer/SummaryResult'
import { useAnalyticsFilters } from '../hooks/useAnalyticsFilters'
import type { AnalyticsFiltersState } from '../utils/analyticsFilters'
import { useWorkflows } from '../hooks/useWorkflows'
import { usePlugins } from '../hooks/usePlugins'
import { useCollections } from '../hooks/useCollections'
import { useSchemas } from '../hooks/useSchemas'
import { useAllViews, useViewSummary } from '../hooks/useViews'
import {
  storedCard,
  useDashboard,
  useSaveDashboard,
} from '../hooks/useDashboard'
import { usePermissions } from '../hooks/useMe'
import type { DashboardCard, DashboardCardShown } from '../api/dashboard'
import type { View } from '../api/views'
import { viewTarget } from '../utils/navTargets'
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

/** The project's Analytics page: one shared list of cards, each a saved
 * analysis (a saved view with a summary, drawn as its table or chart) or a
 * built-in widget, small (half the page) or wide. Anyone who may change
 * records somewhere may edit it (**Edit page**: reorder, resize, retitle,
 * remove, **Add a card**, then **Done**, saved as one change); it syncs and
 * is in Activity. The filter bar governs the built-in widgets. */
export default function AnalyticsPage() {
  const { filters, setFilters, resetFilters } = useAnalyticsFilters()
  const { data: workflows } = useWorkflows()
  const { data: plugins } = usePlugins()
  const { data: collections } = useCollections()
  const { data: schemas } = useSchemas()
  const page = useDashboard()
  const save = useSaveDashboard()
  const { canSomewhere, why } = usePermissions()
  const mayEdit = canSomewhere('write_records')
  const [sp, setSp] = useSearchParams()
  const editing = sp.get('edit') === '1' && mayEdit
  const [draft, setDraft] = useState<DashboardCardShown[] | null>(null)

  const cards = (editing ? draft : null) ?? page.data?.cards ?? []
  const names = page.data?.widgets ?? {}

  const setEditing = (on: boolean) => {
    setDraft(on ? (page.data?.cards ?? []) : null)
    setSp(
      (prev) => {
        const out = new URLSearchParams(prev)
        if (on) out.set('edit', '1')
        else out.delete('edit')
        return out
      },
      { replace: true },
    )
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

  return (
    <Page
      title="Analytics"
      info="One page for the whole project. Put your saved analyses on it beside the built-in charts: make an analysis from a collection's records (Summary, then Save analysis…), then Edit page › Add a card."
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
          <Button
            size="sm"
            onClick={() => setEditing(true)}
            disabled={!mayEdit || !page.data}
            title={mayEdit ? undefined : why('write_records')}
          >
            Edit page
          </Button>
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

      {page.error ? (
        <ErrorState message={errorMessage(page.error)} />
      ) : !page.data ? (
        <Skeleton className="h-64" />
      ) : editing ? (
        <EditCards
          cards={cards}
          names={names}
          onChange={setDraft}
          onCard={change}
          error={save.error}
        />
      ) : cards.length === 0 ? (
        <EmptyState
          title="Nothing on this page yet"
          message="To make an analysis, open a collection's records, choose Summary, pick what to count and how to group it, and press Save analysis… Then come back here, press Edit page, and Add a card."
          action={
            mayEdit ? (
              <Button size="sm" onClick={() => setEditing(true)}>
                Edit page
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {cards.map((c) => (
            <div
              key={c.id}
              className={c.size === 'wide' ? 'lg:col-span-2' : undefined}
            >
              {c.kind === 'analysis' ? (
                <AnalysisCard card={c} />
              ) : (
                <>
                  {c.title && (
                    <h2 className="mb-2 text-sm font-semibold text-fg">
                      {c.title}
                    </h2>
                  )}
                  {WIDGETS[c.widget ?? '']?.(filters) ?? (
                    <WidgetCard title={c.widget ?? 'Widget'}>
                      <p className="text-sm text-fg-muted">
                        This version of civex doesn't know this chart.
                      </p>
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

/** The name a card goes by on the page and in the editor. */
function cardName(c: DashboardCardShown, names: Record<string, string>) {
  if (c.title) return c.title
  if (c.kind === 'analysis')
    return c.analysis?.name ?? 'An analysis that was deleted'
  return names[c.widget ?? ''] ?? c.widget ?? 'Widget'
}

/** A saved analysis worked out now, as its table or chart, with a way to
 * open it in the explorer (where it can be changed). */
function AnalysisCard({ card }: { card: DashboardCardShown }) {
  const view = card.analysis
  if (!view)
    return (
      <WidgetCard title={card.title ?? 'Analysis'}>
        <p className="text-sm text-fg-muted">
          The analysis this card showed was deleted. Restore it from Activity,
          or take the card off the page.
        </p>
      </WidgetCard>
    )
  return <ShownAnalysis view={view} title={card.title ?? view.name} />
}

function ShownAnalysis({ view, title }: { view: View; title: string }) {
  const { data, isLoading, error } = useViewSummary(view.schema_name, view.name)
  const opens = viewTarget(
    { id: view.schema_id, name: view.schema_name },
    view.name,
    view,
  ).to
  const s = view.summary
  return (
    <WidgetCard
      title={title}
      description={`An analysis of ${view.schema_name} records, saved from the explorer.`}
      viewRunsTo={opens}
      viewRunsLabel="Open in explorer"
    >
      <SummaryResult
        data={data}
        isLoading={isLoading}
        error={error}
        show={s?.show ?? 'table'}
        sort={s?.sort ?? null}
        chartMeasure={s?.chart_measure ?? null}
      />
    </WidgetCard>
  )
}

/** The page being edited: the cards in order (drag by the grip, or the
 * arrows), each with its size, its own title and a way off the page, and
 * **Add a card** for the saved analyses and widgets not on it. */
function EditCards({
  cards,
  names,
  onChange,
  onCard,
  error,
}: {
  cards: DashboardCardShown[]
  names: Record<string, string>
  onChange: (next: DashboardCardShown[]) => void
  onCard: (id: string, patch: Partial<DashboardCard>) => void
  error: unknown
}) {
  const { data: views } = useAllViews()
  const analyses = (views ?? []).filter((v) => v.summary)
  const onPage = new Set(cards.map((c) => c.view ?? c.widget))
  const newId = (base: string) => {
    let id = base
    for (let n = 2; cards.some((c) => c.id === id); n++) id = `${base}-${n}`
    return id
  }
  const add = (card: DashboardCardShown) => onChange([...cards, card])

  const items: MenuEntry[] = [{ heading: 'Saved analyses' }]
  const free = analyses.filter((v) => !onPage.has(v.id))
  if (free.length === 0)
    items.push({
      label:
        analyses.length === 0
          ? 'None saved yet'
          : 'Every saved analysis is on the page',
      hint:
        analyses.length === 0
          ? "Open a collection's records, choose Summary, then Save analysis…"
          : undefined,
      disabled: true,
      onClick: () => {},
    })
  for (const v of free)
    items.push({
      label: v.name,
      hint: `Of ${v.schema_name} records`,
      icon: BarChart3,
      onClick: () =>
        add({
          id: newId(`analysis-${v.id.slice(0, 8)}`),
          kind: 'analysis',
          size: 'small',
          view: v.id,
          analysis: v,
        }),
    })
  const widgetsOff = Object.entries(names).filter(([k]) => !onPage.has(k))
  if (widgetsOff.length > 0) {
    items.push({ heading: 'Built-in charts' })
    for (const [key, name] of widgetsOff)
      items.push({
        label: name,
        onClick: () =>
          add({
            id: newId(`widget-${key}`),
            kind: 'widget',
            size: key === 'ai_tokens' ? 'wide' : 'small',
            widget: key,
          }),
      })
  }

  return (
    <div className="space-y-3">
      {error != null && <ErrorState message={errorMessage(error)} />}
      {cards.length === 0 ? (
        <p className="text-sm text-fg-muted">
          No cards. Add one below, or press Done to leave the page empty.
        </p>
      ) : (
        <SortableList
          label="Cards on the page"
          items={cards}
          getKey={(c) => c.id}
          getLabel={(c) => cardName(c, names)}
          onReorder={(next) => onChange(next)}
          moveButtons="always"
          renderItem={(c) => (
            <div className="flex flex-wrap items-center gap-3 py-1">
              <span className="min-w-0 flex-1 truncate text-sm font-medium">
                {c.kind === 'analysis' && (
                  <BarChart3
                    size={14}
                    className="mr-1 inline text-fg-subtle"
                    aria-hidden="true"
                  />
                )}
                {c.kind === 'analysis'
                  ? (c.analysis?.name ?? 'An analysis that was deleted')
                  : (names[c.widget ?? ''] ?? c.widget)}
              </span>
              <Field label={`Title for ${cardName(c, names)}`} hideLabel>
                <Input
                  size="sm"
                  className="w-48"
                  placeholder="Its own name"
                  value={c.title ?? ''}
                  maxLength={200}
                  onChange={(e) =>
                    onCard(c.id, { title: e.target.value || null })
                  }
                />
              </Field>
              <SegmentedControl
                size="sm"
                label={`Size of ${cardName(c, names)}`}
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
                aria-label={`Take ${cardName(c, names)} off the page`}
                onClick={() => onChange(cards.filter((o) => o.id !== c.id))}
              />
            </div>
          )}
        />
      )}
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
      <p className="text-xs text-fg-muted">
        Changes are saved for everyone when you press Done. The filters above
        the page apply to the built-in charts.
      </p>
    </div>
  )
}
