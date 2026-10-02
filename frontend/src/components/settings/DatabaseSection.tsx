import { useDbStatus } from '../../hooks/useDb'
import { ErrorState, Skeleton } from '../ui'
import { errorMessage } from '../../lib/errors'
import { AdvancedDatabase } from './database/AdvancedDatabase'
import { CurrentDatabaseCard } from './database/CurrentDatabaseCard'
import { MoveHistory } from './database/MoveHistory'

export default function DatabaseSection() {
  const { data: status, isLoading, error } = useDbStatus()

  if (isLoading)
    return (
      <div className="space-y-6" aria-hidden="true">
        <div className="space-y-2">
          <Skeleton className="h-5 w-24" />
          <Skeleton className="h-4 w-80" />
        </div>
        <Skeleton className="h-28 w-full" />
      </div>
    )
  if (error || !status)
    return (
      <ErrorState
        message={error ? errorMessage(error) : 'Failed to load database status'}
      />
    )

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-fg">Database</h2>
        <p className="text-sm text-fg-muted mt-1">
          Where this project&rsquo;s records are stored. You can move them to
          another kind of database at any time; your original is kept.
        </p>
      </div>
      <CurrentDatabaseCard />
      <MoveHistory />
      <AdvancedDatabase />
    </div>
  )
}
