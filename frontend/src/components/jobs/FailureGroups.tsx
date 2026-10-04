import type { FailureGroup } from '../../api/workflows'
import { Badge, Button, Disclosure } from '../ui'
import { RefreshCw } from '../ui/icons'
import { truncate } from '../../utils/runFilter'

/** Why runs failed, in a few lines: the failed runs a filter covers, grouped by
 * workflow and what went wrong, with how many each. A thousand failures usually
 * come from a handful of causes, so this is where to start; each cause opens
 * its runs, or repeats them once whatever caused it is fixed. */
export function FailureGroups({
  groups,
  open,
  onShow,
  onRerun,
  rerunning,
}: {
  groups: FailureGroup[]
  /** Open by default, when the list is already looking at failures. */
  open: boolean
  onShow: (group: FailureGroup) => void
  onRerun: (group: FailureGroup) => void
  rerunning: boolean
}) {
  if (groups.length === 0) return null
  const runs = groups.reduce((n, g) => n + g.count, 0)
  return (
    <Disclosure
      defaultOpen={open}
      summary={
        <span className="text-sm">
          <span className="font-medium text-danger">
            {runs.toLocaleString()} failed {runs === 1 ? 'run' : 'runs'}
          </span>{' '}
          <span className="text-fg-muted">
            in {groups.length} {groups.length === 1 ? 'group' : 'groups'}: why
            they failed
          </span>
        </span>
      }
    >
      <ul className="divide-y divide-border-muted">
        {groups.map((g, i) => (
          <li
            key={i}
            className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm"
          >
            <Badge variant="danger">{g.count.toLocaleString()}</Badge>
            <span className="font-medium">{g.workflow}</span>
            {g.step && (
              <span className="text-xs text-fg-muted">in {g.step}</span>
            )}
            <span
              className="min-w-0 flex-1 truncate text-fg-muted"
              title={g.message ?? undefined}
            >
              {g.message ? truncate(g.message) : (g.kind ?? 'Unknown error')}
            </span>
            {g.kind && (
              <span className="font-mono text-xs text-fg-subtle">{g.kind}</span>
            )}
            <Button size="sm" onClick={() => onShow(g)}>
              Show
            </Button>
            <Button size="sm" disabled={rerunning} onClick={() => onRerun(g)}>
              <RefreshCw size={12} /> Re-run {g.count.toLocaleString()}
            </Button>
          </li>
        ))}
      </ul>
    </Disclosure>
  )
}
