import DatabaseSection from '../components/settings/DatabaseSection'
import StorageSection from '../components/settings/StorageSection'
import ThemeSection from '../components/settings/ThemeSection'

export default function SettingsPage() {
  return (
    <div className="space-y-10">
      <h1 className="text-xl font-semibold text-fg">Settings</h1>
      <ThemeSection />
      <hr className="border-border" />
      <DatabaseSection />
      <hr className="border-border" />
      <StorageSection />
    </div>
  )
}
