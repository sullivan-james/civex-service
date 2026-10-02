/** A byte count as KB / MB / GB / TB, for disk sizes. */
export function formatSize(bytes: number | null | undefined): string {
  if (bytes == null) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit++
  }
  const digits = unit === 0 || value >= 100 ? 0 : 1
  return `${value.toFixed(digits)} ${units[unit]}`
}

/** "/home/me/data" -> [{"/", "/"}, {"home", "/home"}, {"me", "/home/me"}, ...];
 * a Windows path starts at its drive instead. */
export function breadcrumbs(path: string): { label: string; path: string }[] {
  const drive = /^[A-Za-z]:/.exec(path)
  const root = drive ? `${drive[0]}/` : '/'
  const parts = path
    .slice(drive ? 3 : 1)
    .split('/')
    .filter(Boolean)
  const crumbs = [{ label: drive ? drive[0] : '/', path: root }]
  let walked = drive ? drive[0] : ''
  for (const part of parts) {
    walked += `/${part}`
    crumbs.push({ label: part, path: walked })
  }
  return crumbs
}
