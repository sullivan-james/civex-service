import { knownTimeZone } from './dates'

const FALLBACK = [
  'UTC',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'Europe/London',
  'Europe/Berlin',
  'Asia/Kolkata',
  'Asia/Tokyo',
  'Australia/Sydney',
]

/** IANA zone names the runtime supports, for a picker. `selected` is always
 * included so an already-saved zone the browser doesn't list still shows. */
export function timeZoneOptions(selected?: string | null): string[] {
  const supported = (
    Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
  ).supportedValuesOf?.('timeZone')
  const names = new Set<string>(['UTC', ...(supported ?? FALLBACK)])
  if (selected && knownTimeZone(selected)) names.add(selected)
  return [...names].sort((a, b) =>
    a === 'UTC' ? -1 : b === 'UTC' ? 1 : a.localeCompare(b),
  )
}
