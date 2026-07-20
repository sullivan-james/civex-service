import DatabaseSection from '../components/settings/DatabaseSection'
import StorageSection from '../components/settings/StorageSection'

export default function SettingsPage() {
  return (
    <div className="space-y-10">
      <h1 className="text-xl font-semibold text-[#1f2328]">Settings</h1>
      <DatabaseSection />
      <hr className="border-[#d0d7de]" />
      <StorageSection />
    </div>
  )
}
