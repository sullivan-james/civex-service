import type { ReactNode } from 'react'
import { InfoTip } from './Tooltip'

/** What a status means at a glance: fine, worth a look, wrong, or simply not
 * here. Every status in the app (a drive's, where a file is, a bar's parts)
 * takes one of these, so the same meaning is always the same colour. */
export type Tone = 'ok' | 'attention' | 'danger' | 'neutral'

export const TONE_BG: Record<Tone, string> = {
  ok: 'bg-success',
  attention: 'bg-attention',
  danger: 'bg-danger',
  neutral: 'bg-fg-subtle',
}

export const TONE_TEXT: Record<Tone, string> = {
  ok: 'text-fg',
  attention: 'text-attention',
  danger: 'text-danger',
  neutral: 'text-fg-muted',
}

/** A small coloured dot. Decorative: the status is always also written out. */
export function StatusDot({ tone }: { tone: Tone }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block h-2 w-2 shrink-0 rounded-full ${TONE_BG[tone]}`}
    />
  )
}

/** A status: its dot and its words, with why (and what to do) in a tooltip
 * rather than on the page. */
export function Status({
  tone,
  children,
  why,
}: {
  tone: Tone
  children: ReactNode
  why?: string
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap ${TONE_TEXT[tone]}`}
    >
      <StatusDot tone={tone} />
      {children}
      {why && <InfoTip label="Why">{why}</InfoTip>}
    </span>
  )
}

/** Parts of a whole as one bar (where a collection's files are, by drive or
 * by place), each part in its status's colour, with a gap between parts so a
 * split shows even when two parts share a colour. */
export function SegmentBar({
  parts,
  label,
  className = 'h-1.5',
}: {
  parts: { key: string; label: string; value: number; tone: Tone }[]
  label: string
  className?: string
}) {
  const total = parts.reduce((n, p) => n + p.value, 0)
  if (total === 0) return null
  return (
    <div
      role="img"
      aria-label={`${label}: ${parts.map((p) => p.label).join(', ')}`}
      className={`flex gap-0.5 overflow-hidden rounded-full bg-canvas-inset ${className}`}
    >
      {parts.map((p) => (
        <div
          key={p.key}
          title={p.label}
          className={TONE_BG[p.tone]}
          style={{ width: `${(Math.max(p.value, 0) / total) * 100}%` }}
        />
      ))}
    </div>
  )
}
