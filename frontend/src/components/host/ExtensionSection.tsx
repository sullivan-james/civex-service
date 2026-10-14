import { useParams } from 'react-router'
import { EmptyState } from '../ui'
import { SlotItem } from './Slot'

/** `/settings/x/<id>`: a Settings section a host's extension registered
 * (`settings.sections`). */
export default function ExtensionSection() {
  const { id = '' } = useParams()
  return (
    <SlotItem
      name="settings.sections"
      id={id}
      fallback={
        <EmptyState
          title="This section isn’t available"
          message="It comes from the server this project is on, and hasn’t loaded. Reload the page to try again."
        />
      }
    />
  )
}
