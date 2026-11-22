interface ChartTooltipPayloadEntry {
  dataKey?: string | number
  name?: string | number
  value?: number | string
  color?: string
  payload?: unknown
}

export interface ChartTooltipProps {
  active?: boolean
  label?: string | number
  payload?: ChartTooltipPayloadEntry[]
  formatValue?: (value: number) => string
  /** Title the tooltip with this key of the hovered row instead of the axis
   * label (a range's full wording rather than its start). */
  labelKey?: string
  formatLabel?: (label: string) => string
}

/** Recharts `content` renderer shared by every primitive in this directory,
 * so tooltips look consistent and stay on theme tokens rather than
 * recharts' default inline styles. */
export function ChartTooltip({
  active,
  label,
  payload,
  formatValue = (value) => String(value),
  labelKey,
  formatLabel = (label) => label,
}: ChartTooltipProps) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload as Record<string, unknown> | undefined
  const title = labelKey
    ? String(row?.[labelKey] ?? label ?? '')
    : label != null
      ? formatLabel(String(label))
      : null

  return (
    <div className="rounded-md border border-border bg-canvas px-3 py-2 text-xs shadow-sm">
      {title != null && <div className="mb-1 font-medium text-fg">{title}</div>}
      <div className="flex flex-col gap-1">
        {payload.map((entry, index) => (
          <div
            key={entry.dataKey ?? index}
            className="flex items-center gap-2 text-fg-muted"
          >
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: entry.color }}
            />
            <span>{entry.name}</span>
            <span className="ml-auto font-medium text-fg">
              {typeof entry.value === 'number'
                ? formatValue(entry.value)
                : entry.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
