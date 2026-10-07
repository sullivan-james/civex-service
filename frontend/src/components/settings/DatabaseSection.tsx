import { useDbMoves, useDbStatus } from '../../hooks/useDb'
import { ErrorState, Skeleton, TabNav, TabPanel, useTabParam } from '../ui'
import { errorMessage } from '../../lib/errors'
import { AdvancedDatabase } from './database/AdvancedDatabase'
import { CurrentDatabaseCard } from './database/CurrentDatabaseCard'
import { HistoryStorageCard } from './database/HistoryStorageCard'
import { OrphansCard } from './database/OrphansCard'
import { MoveHistory } from './database/MoveHistory'

const DB_TABS = [
  { id: 'current' },
  { id: 'history' },
  { id: 'advanced' },
] as const

export default function DatabaseSection() {
  const { data: status, isLoading, error } = useDbStatus()
  const { data: moves } = useDbMoves()
  const [tab, setTab] = useTabParam(DB_TABS, 'current')
  const hasHistory = !!moves && moves.length > 0
  const shownTab = tab === 'history' && !hasHistory ? 'current' : tab

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
    <div className="space-y-5">
      <TabNav
        label="Database"
        value={shownTab}
        onChange={setTab}
        tabs={[
          { id: 'current' as const, label: 'Current' },
          ...(hasHistory
            ? [{ id: 'history' as const, label: `History (${moves.length})` }]
            : []),
          { id: 'advanced' as const, label: 'Advanced' },
        ]}
      />
      <TabPanel id="current" value={shownTab}>
        <div className="space-y-5">
          <CurrentDatabaseCard />
          <HistoryStorageCard />
          <OrphansCard />
        </div>
      </TabPanel>
      <TabPanel id="history" value={shownTab}>
        <MoveHistory />
      </TabPanel>
      <TabPanel id="advanced" value={shownTab}>
        <AdvancedDatabase />
      </TabPanel>
    </div>
  )
}
