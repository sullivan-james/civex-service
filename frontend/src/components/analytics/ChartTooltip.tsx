interface ChartTooltipPayloadEntry {
  dataKey?: string | number
  name?: string | number
  value?: number | string
  color?: string
}

export interface ChartTooltipProps {
  active?: boolean
  label?: string | number
  payload?: ChartTooltipPayloadEntry[]
  formatValue?: (value: number) => string
}

/** Recharts `content` renderer shared by every primitive in this directory,
 * so tooltips look consistent and stay on theme tokens rather than
 * recharts' default inline styles. */
export function ChartTooltip({
  active,
  label,
  payload,
  formatValue = (value) => String(value),
}: ChartTooltipProps) {
  if (!active || !payload?.length) return null

  return (
    <div className="rounded-md border border-border bg-canvas px-3 py-2 text-xs shadow-sm">
      {label != null && <div className="mb-1 font-medium text-fg">{label}</div>}
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
