import { useState } from 'react'
import { auditApi, type AuditEvent } from '../../api/audit'
import { useRemoteStatus } from '../../hooks/useRemote'
import { describeAuditEvent } from '../../utils/activityAudit'
import { formatTimestamp } from '../../utils/dates'
import { errorMessage } from '../../lib/errors'
import { Badge, Button } from '../ui'

/** Pages that come back empty (a run this device may not read) are skipped
 * through, this many at a time, before asking the person to carry on. */
const SKIP_EMPTY = 10

/**
 * History from before this project was copied. None of it is downloaded: each
 * page is read from the server when asked for and is not kept, so what it costs
 * follows what is looked at. Offline, it says where the rest is.
 */
export function EarlierActivity({ under }: { under?: string }) {
  const { data: status } = useRemoteStatus()
  const [events, setEvents] = useState<AuditEvent[]>([])
  // undefined: not asked yet; null: that was the start.
  const [next, setNext] = useState<number | null | undefined>(undefined)
  const [offline, setOffline] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)

  if (!status?.earlier_history) return null

  const load = async () => {
    setBusy(true)
    setFailed(null)
    try {
      let before = next === undefined ? null : next
      let got: AuditEvent[] = []
      for (let i = 0; i < SKIP_EMPTY; i++) {
        const page = await auditApi.earlier(before, 25, under)
        setOffline(page.offline)
        if (page.offline) return
        got = page.items
        before = page.next_before
        setNext(before)
        if (got.length > 0 || before == null) break
      }
      setEvents((prev) => [...prev, ...got])
    } catch (e) {
      setFailed(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2" aria-busy={busy}>
      {events.length > 0 && (
        <ul className="divide-y divide-border rounded-md border border-border text-sm">
          {events.map((e) => {
            const { title } = describeAuditEvent(e)
            const who = e.actor ?? e.entry?.actor
            return (
              <li
                key={e.id}
                className="flex flex-wrap items-center gap-2 px-3 py-2"
              >
                <span className="w-36 truncate font-medium text-fg">
                  {who ?? '—'}
                </span>
                <Badge>
                  {e.entry ? e.entry.action : (e.batch?.kind ?? '')}
                </Badge>
                <span className="min-w-0 flex-1">{title}</span>
                <span className="whitespace-nowrap text-fg-muted">
                  {formatTimestamp(e.timestamp)}
                </span>
              </li>
            )
          })}
        </ul>
      )}
      {offline ? (
        <p className="text-sm text-fg-muted">
          Earlier activity is on the server.{' '}
          <Button size="sm" onClick={load} disabled={busy}>
            Try again
          </Button>
        </p>
      ) : failed ? (
        <p className="text-sm text-danger">{failed}</p>
      ) : next === null ? (
        events.length === 0 ? (
          <p className="text-sm text-fg-muted">Nothing earlier.</p>
        ) : null
      ) : (
        <Button size="sm" onClick={load} disabled={busy}>
          {busy
            ? 'Loading…'
            : next === undefined
              ? 'Show earlier activity'
              : 'Show more'}
        </Button>
      )}
    </div>
  )
}
