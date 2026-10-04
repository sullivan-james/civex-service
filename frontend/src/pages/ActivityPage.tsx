import { ActivityFeed } from '../components/audit/ActivityFeed'
import { Page } from '../components/ui'
import { useRetentionSettings } from '../hooks/useUISettings'

/** Everything that changed in the project. One list: a bulk operation is one
 * line, and "Deleted" narrows it to what can still be restored. It is filtered
 * like the records explorer, and the same list is a record's History and a
 * collection's Activity. */
export default function ActivityPage() {
  const { data: retention } = useRetentionSettings()
  return (
    <Page
      title="Activity"
      info={
        retention
          ? `Changes are kept in full. A deleted item can be restored until it is permanently deleted, which is always a separate step (items older than ${retention.purge_after_days} day${retention.purge_after_days === 1 ? '' : 's'} can be cleaned up).`
          : undefined
      }
    >
      <ActivityFeed emptyMessage="Changes to your data and structure will appear here." />
    </Page>
  )
}
