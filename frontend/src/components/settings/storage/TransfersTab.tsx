import { useTransfers } from '../../../hooks/useTransfers'
import { errorMessage } from '../../../lib/errors'
import { queueAhead } from '../../../utils/transfers'
import { ErrorState, Skeleton, Subheading } from '../../ui'
import { TransferCard } from './TransferCard'

/** The moves that have been started, newest first, each with its progress and
 * what can be done with it. Starting one is on the Tasks page above. */
export function TransfersTab() {
  const { data, isLoading, error } = useTransfers()

  if (isLoading) return <Skeleton className="h-24 w-full" />
  if (error) return <ErrorState message={errorMessage(error)} />
  const ahead = queueAhead(data ?? [])

  return (
    <section aria-label="Moves" className="space-y-3">
      <Subheading as="h3">Moves</Subheading>
      {data && data.length > 0 ? (
        <ul className="space-y-3">
          {data.map((t) => (
            <TransferCard key={t.id} t={t} ahead={ahead.get(t.id)} />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-fg-muted">
          No moves yet. One you start appears here, and across the bottom of the
          screen while it runs.
        </p>
      )}
    </section>
  )
}
