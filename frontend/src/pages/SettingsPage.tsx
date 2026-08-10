import { Page } from '../components/ui'
import DatabaseSection from '../components/settings/DatabaseSection'
import StorageSection from '../components/settings/StorageSection'
import ThemeSection from '../components/settings/ThemeSection'
import AdvancedSection from '../components/settings/AdvancedSection'

export default function SettingsPage() {
  return (
    <Page title="Settings">
      <ThemeSection />
      <hr className="border-border" />
      <DatabaseSection />
      <hr className="border-border" />
      <StorageSection />
      <hr className="border-border" />
      <AdvancedSection />
    </Page>
  )
}
