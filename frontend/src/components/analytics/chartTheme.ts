// Shared styling for the recharts-based primitives in this directory, so
// each chart doesn't re-derive its own axis/grid/tooltip look. Colours are
// CSS custom properties (not Tailwind classes), which SVG presentation
// attributes resolve at paint time — this is how the primitives stay in
// sync with light/dark theme switches without re-rendering.

export const CHART_PALETTE = [
  'var(--color-chart-1)',
  'var(--color-chart-2)',
  'var(--color-chart-3)',
  'var(--color-chart-4)',
  'var(--color-chart-5)',
]

export function seriesColor(index: number, override?: string): string {
  return override ?? CHART_PALETTE[index % CHART_PALETTE.length]
}

export const chartGridProps = {
  stroke: 'var(--color-border-muted)',
  strokeDasharray: '3 3',
  vertical: false,
}

export const chartAxisTickStyle = {
  fill: 'var(--color-fg-muted)',
  fontSize: 12,
}

export const chartAxisLineProps = {
  stroke: 'var(--color-border)',
}

/** Legend above the plot, in muted text (identity is the swatch, never the
 * text colour). */
export const chartLegendProps = {
  verticalAlign: 'top' as const,
  align: 'left' as const,
  iconType: 'circle' as const,
  iconSize: 8,
  wrapperStyle: {
    fontSize: 12,
    color: 'var(--color-fg-muted)',
    paddingBottom: 4,
  },
}

/** A value axis' title (a measure and its unit), along the axis. */
export function chartValueAxisLabel(text: string | undefined, axis: 'x' | 'y') {
  if (!text) return undefined
  return axis === 'y'
    ? {
        value: text,
        angle: -90,
        position: 'insideLeft' as const,
        offset: -4,
        style: {
          textAnchor: 'middle' as const,
          fill: 'var(--color-fg-muted)',
          fontSize: 12,
        },
      }
    : {
        value: text,
        position: 'insideBottom' as const,
        offset: -4,
        style: { fill: 'var(--color-fg-muted)', fontSize: 12 },
      }
}
