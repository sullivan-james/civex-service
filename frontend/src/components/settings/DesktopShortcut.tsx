import { useCreateShortcut, useShortcut } from '../../hooks/useShortcut'
import { errorMessage } from '../../lib/errors'
import { Button, InfoTip } from '../ui'
import { Check, Monitor } from '../ui/icons'

/** Adds a Desktop icon that starts civex for this project and opens it.
 * `prompt` shows it only while there is none (for the first-run page); the
 * settings page shows the state either way. */
export function DesktopShortcut({ prompt = false }: { prompt?: boolean }) {
  const { data } = useShortcut()
  const create = useCreateShortcut()
  if (!data) return null
  // No Desktop folder: nothing to offer on the first-run page.
  if (prompt && (data.exists || data.path === null)) return null

  return (
    <div className="flex flex-wrap items-center gap-2">
      {data.exists ? (
        <span className="inline-flex items-center gap-1 text-sm text-fg">
          <Check size={16} className="text-success" aria-hidden="true" />
          Desktop shortcut added
        </span>
      ) : (
        <Button
          size="sm"
          disabled={create.isPending || data.path === null}
          onClick={() => create.mutate()}
        >
          <Monitor size={14} /> Add desktop shortcut
        </Button>
      )}
      <InfoTip>
        A Desktop icon that starts civex for this project and opens it in your
        browser. It opens a window showing civex running; close that window to
        stop it.
      </InfoTip>
      {create.error && (
        <span role="alert" className="text-sm text-danger">
          {errorMessage(create.error)}
        </span>
      )}
    </div>
  )
}
