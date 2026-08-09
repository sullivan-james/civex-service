import * as restrictions from '../../utils/restrictions'

export function RestrictionsSummary({
  restrictions: fieldRestrictions,
  type,
}: {
  restrictions: Record<string, unknown>
  type: string
}) {
  const summary = restrictions.summarise(fieldRestrictions, type)
  if (!summary) return null
  return <span className="text-xs text-fg-muted leading-tight">{summary}</span>
}
