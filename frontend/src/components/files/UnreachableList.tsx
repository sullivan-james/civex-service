import type { UnavailableGroup } from '../../api/fileAccess'

const plural = (n: number, word: string) =>
  `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`

/** What can't be reached, by drive, in the drive's own words, with what to do. */
export function UnreachableList({ groups }: { groups: UnavailableGroup[] }) {
  return (
    <ul className="space-y-3 text-sm">
      {groups.map((g) => (
        <li key={`${g.volume}-${g.reason}`}>
          <p className="font-medium text-fg">
            {plural(g.files, 'file')}{' '}
            {g.volume ? `on “${g.volume}”` : 'not stored on any known drive'}
          </p>
          {g.reason && <p className="text-fg-muted">{g.reason}</p>}
          {g.fix && <p className="text-fg">{g.fix}</p>}
          {g.records.length > 0 && (
            <p className="text-xs text-fg-muted">
              {g.records.join(', ')}
              {g.files > g.records.length ? ', …' : ''}
            </p>
          )}
        </li>
      ))}
    </ul>
  )
}
