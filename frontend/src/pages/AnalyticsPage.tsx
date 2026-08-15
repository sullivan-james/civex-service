import { useAnalyticsFilters } from '../hooks/useAnalyticsFilters'
import { Page } from '../components/ui'
import { AnalyticsFilterBar, AiTokenUsageWidget } from '../components/analytics'

export default function AnalyticsPage() {
  const { filters, setFilters, resetFilters } = useAnalyticsFilters()

  return (
    <Page title="Analytics" description="Usage and activity across the project">
      <AnalyticsFilterBar
        filters={filters}
        onChange={setFilters}
        onReset={resetFilters}
      />
      <AiTokenUsageWidget filters={filters} />
    </Page>
  )
}
