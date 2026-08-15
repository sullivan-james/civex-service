import { useMemo, useState } from 'react'
import { useAiTokenUsage } from '../../hooks/useAiTokenUsage'
import type { AnalyticsFiltersState } from '../../utils/analyticsFilters'
import { Field, Select, Skeleton, ErrorState, EmptyState } from '../ui'
import { errorMessage } from '../../lib/errors'
import { TimeSeriesChart, type TimeSeriesPoint } from './TimeSeriesChart'
import { StatTile } from './StatTile'
import { formatCompactNumber } from './format'

export interface AiTokenUsageWidgetProps {
  filters: AnalyticsFiltersState
}

function formatBucketLabel(value: string): string {
  const parsed = new Date(value)
  return isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

/** Token usage over time, split into input vs. output series, with
 * provider/model as a widget-local filter -- unlike the shared filter
 * bar's dimensions (dataset, schema, workflow, ...), provider/model are
 * meaningful only to AI usage data, so they don't belong in the
 * cross-domain filter contract every other analytics endpoint accepts. */
export function AiTokenUsageWidget({ filters }: AiTokenUsageWidgetProps) {
  const [provider, setProvider] = useState<string | null>(null)
  const [model, setModel] = useState<string | null>(null)

  // Unfiltered by provider/model, so the dropdown options stay stable
  // (covering every combination in range) regardless of the current
  // selection. When no filter is picked this is the same query as the one
  // below, so TanStack Query serves both from one cached fetch.
  const optionsQuery = useAiTokenUsage(filters, null, null)
  const usageQuery = useAiTokenUsage(filters, provider, model)

  const { providerOptions, modelOptions } = useMemo(() => {
    const items = optionsQuery.data?.items ?? []
    const providers = new Set<string>()
    const models = new Set<string>()
    for (const item of items) {
      providers.add(item.provider)
      if (!provider || item.provider === provider) models.add(item.model)
    }
    return {
      providerOptions: [...providers].sort(),
      modelOptions: [...models].sort(),
    }
  }, [optionsQuery.data, provider])

  const { points, totalInput, totalOutput } = useMemo(() => {
    const items = usageQuery.data?.items ?? []
    const byBucket = new Map<string, { input: number; output: number }>()
    for (const item of items) {
      const totals = byBucket.get(item.bucket) ?? { input: 0, output: 0 }
      totals.input += item.input_tokens
      totals.output += item.output_tokens
      byBucket.set(item.bucket, totals)
    }
    const sortedEntries = [...byBucket.entries()].sort(([a], [b]) =>
      a.localeCompare(b),
    )
    const sortedPoints: TimeSeriesPoint[] = sortedEntries.map(
      ([bucket, totals]) => ({
        date: bucket,
        input_tokens: totals.input,
        output_tokens: totals.output,
      }),
    )
    const totalInput = sortedEntries.reduce((sum, [, t]) => sum + t.input, 0)
    const totalOutput = sortedEntries.reduce((sum, [, t]) => sum + t.output, 0)
    return { points: sortedPoints, totalInput, totalOutput }
  }, [usageQuery.data])

  function handleProviderChange(next: string | null) {
    setProvider(next)
    setModel(null)
  }

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border bg-canvas p-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-fg">AI token usage</h3>
          <p className="text-xs text-fg-subtle">
            Input vs. output tokens over time, from recorded provider calls.
          </p>
        </div>
        <div className="flex gap-2">
          <Field label="Provider">
            <Select
              value={provider ?? ''}
              onChange={(e) => handleProviderChange(e.target.value || null)}
            >
              <option value="">All providers</option>
              {providerOptions.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Model">
            <Select
              value={model ?? ''}
              onChange={(e) => setModel(e.target.value || null)}
            >
              <option value="">All models</option>
              {modelOptions.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </div>

      {usageQuery.isLoading && <Skeleton className="h-60 w-full" />}
      {usageQuery.error && (
        <ErrorState message={errorMessage(usageQuery.error)} />
      )}
      {!usageQuery.isLoading && !usageQuery.error && points.length === 0 && (
        <EmptyState
          title="No AI usage in range"
          message="Adjust the date range or filters to see token usage."
        />
      )}
      {!usageQuery.isLoading && !usageQuery.error && points.length > 0 && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:max-w-md">
            <StatTile
              label="Input tokens"
              value={formatCompactNumber(totalInput)}
            />
            <StatTile
              label="Output tokens"
              value={formatCompactNumber(totalOutput)}
            />
          </div>
          <TimeSeriesChart
            data={points}
            series={[
              { key: 'input_tokens', label: 'Input tokens' },
              { key: 'output_tokens', label: 'Output tokens' },
            ]}
            formatValue={formatCompactNumber}
            formatXAxis={formatBucketLabel}
          />
        </>
      )}
      <p className="text-xs text-fg-subtle">
        Showing token counts only -- estimated cost isn&apos;t shown because no
        per-model pricing source exists in this project yet.
      </p>
    </div>
  )
}
