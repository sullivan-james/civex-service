/** Convert a stored UTC ISO datetime string to a value for <input type="datetime-local">. */
export function utcToDatetimeLocal(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** Convert a <input type="datetime-local"> value (browser local time) to a UTC ISO string. */
export function datetimeLocalToUTC(local: string): string {
  if (!local) return ''
  return new Date(local).toISOString()
}
