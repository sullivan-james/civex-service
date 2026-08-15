import { Field, Select, Input, Button, FormGrid, FormFooter } from '../ui'
import { utcToDatetimeLocal, datetimeLocalToUTC } from '../../utils/dates'
import type { AnalyticsBucket, AnalyticsFiltersState } from '../../utils/analyticsFilters'

export interface AnalyticsFilterOption {
  value: string
  label: string
}

const BUCKET_OPTIONS: AnalyticsFilterOption[] = [
  { value: 'day', label: 'Day' },
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
]

export interface AnalyticsFilterBarProps {
  filters: AnalyticsFiltersState
  onChange: (patch: Partial<AnalyticsFiltersState>) => void
  onReset?: () => void
  datasetOptions?: AnalyticsFilterOption[]
  schemaOptions?: AnalyticsFilterOption[]
  workflowOptions?: AnalyticsFilterOption[]
  pluginOptions?: AnalyticsFilterOption[]
  statusOptions?: AnalyticsFilterOption[]
  triggerOptions?: AnalyticsFilterOption[]
  className?: string
}

function DimensionSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string | null
  options: AnalyticsFilterOption[]
  onChange: (value: string | null) => void
}) {
  return (
    <Field label={label} span={4}>
      <Select
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">All</option>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </Select>
    </Field>
  )
}

/** Presentational, page-agnostic filter bar for the analytics dashboard --
 * every dimension it exposes maps 1:1 to the shared `AnalyticsFilters`
 * query-param contract every `/analytics/*` endpoint accepts. It has no
 * opinion on where `filters` comes from or where `onChange` writes to, so
 * it can sit above any combination of widgets: wire it to
 * `useAnalyticsFilters()` for URL-synced state, or to plain component state
 * in a test/storybook context. */
export function AnalyticsFilterBar({
  filters,
  onChange,
  onReset,
  datasetOptions = [],
  schemaOptions = [],
  workflowOptions = [],
  pluginOptions = [],
  statusOptions = [],
  triggerOptions = [],
  className = '',
}: AnalyticsFilterBarProps) {
  return (
    <FormGrid
      className={`p-4 border border-border rounded-md bg-canvas-subtle ${className}`}
    >
      <Field label="From" span={4}>
        <Input
          type="datetime-local"
          value={utcToDatetimeLocal(filters.start)}
          onChange={(e) =>
            e.target.value &&
            onChange({ start: datetimeLocalToUTC(e.target.value) })
          }
        />
      </Field>

      <Field label="To" span={4}>
        <Input
          type="datetime-local"
          value={utcToDatetimeLocal(filters.end)}
          onChange={(e) =>
            e.target.value &&
            onChange({ end: datetimeLocalToUTC(e.target.value) })
          }
        />
      </Field>

      <Field label="Bucket" span={4}>
        <Select
          value={filters.bucket}
          onChange={(e) =>
            onChange({ bucket: e.target.value as AnalyticsBucket })
          }
        >
          {BUCKET_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </Select>
      </Field>

      <DimensionSelect
        label="Dataset"
        value={filters.dataset}
        options={datasetOptions}
        onChange={(dataset) => onChange({ dataset })}
      />
      <DimensionSelect
        label="Schema"
        value={filters.schema}
        options={schemaOptions}
        onChange={(schema) => onChange({ schema })}
      />
      <DimensionSelect
        label="Workflow"
        value={filters.workflowId}
        options={workflowOptions}
        onChange={(workflowId) => onChange({ workflowId })}
      />
      <DimensionSelect
        label="Plugin"
        value={filters.pluginId}
        options={pluginOptions}
        onChange={(pluginId) => onChange({ pluginId })}
      />
      <DimensionSelect
        label="Status"
        value={filters.status}
        options={statusOptions}
        onChange={(status) => onChange({ status })}
      />
      <DimensionSelect
        label="Trigger"
        value={filters.trigger}
        options={triggerOptions}
        onChange={(trigger) => onChange({ trigger })}
      />

      {onReset && (
        <FormFooter>
          <Button size="sm" onClick={onReset}>
            Reset filters
          </Button>
        </FormFooter>
      )}
    </FormGrid>
  )
}
