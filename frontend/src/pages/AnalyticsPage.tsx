import { Page } from '../components/ui'
import {
  AnalyticsFilterBar,
  JobSuccessRateWidget,
  PluginFailuresWidget,
  DurationDistributionWidget,
  TriggerBreakdownWidget,
  AiTokenUsageWidget,
  RecordGrowthWidget,
  RecordCountsWidget,
  StorageUsageWidget,
  SchemaLintWidget,
} from '../components/analytics'
import { useAnalyticsFilters } from '../hooks/useAnalyticsFilters'
import { useWorkflows } from '../hooks/useWorkflows'
import { usePlugins } from '../hooks/usePlugins'
import { useCollections } from '../hooks/useCollections'
import { useSchemas } from '../hooks/useSchemas'

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

/** Dashboard for data/schema growth and workflow reliability: record
 * growth and counts, storage usage, schema-naming health, plus job
 * success/failure rate, failures by plugin, step duration distribution,
 * and runs by trigger -- each widget summarizes over the shared,
 * URL-synced filter bar and links out to its own detail view rather than
 * duplicating it here. */
export default function AnalyticsPage() {
  const { filters, setFilters, resetFilters } = useAnalyticsFilters()
  const { data: workflows } = useWorkflows()
  const { data: plugins } = usePlugins()
  const { data: collections } = useCollections()
  const { data: schemas } = useSchemas()

  return (
    <Page
      title="Analytics"
      description="Data growth, schema health, and workflow reliability over the selected range"
    >
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
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <RecordGrowthWidget filters={filters} />
        <RecordCountsWidget filters={filters} />
        <StorageUsageWidget />
        <SchemaLintWidget />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <JobSuccessRateWidget filters={filters} />
        <PluginFailuresWidget filters={filters} />
        <DurationDistributionWidget filters={filters} />
        <TriggerBreakdownWidget filters={filters} />
      </div>
      <AiTokenUsageWidget filters={filters} />
    </Page>
  )
}
