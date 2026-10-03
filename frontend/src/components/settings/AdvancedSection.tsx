import { useId } from 'react'
import { useUISettings, useSetShowAdvanced } from '../../hooks/useUISettings'
import { Button, Checkbox, Skeleton } from '../ui'
import { DesktopShortcut } from './DesktopShortcut'

export default function AdvancedSection() {
  const { data: settings, isLoading } = useUISettings()
  const setShowAdvanced = useSetShowAdvanced()
  const checkboxId = useId()

  return (
    <div className="space-y-3">
      {isLoading ? (
        <Skeleton className="h-5 w-64" />
      ) : (
        <label
          htmlFor={checkboxId}
          className="flex items-center gap-2 text-sm text-fg cursor-pointer w-fit"
        >
          <Checkbox
            id={checkboxId}
            checked={settings?.show_advanced ?? false}
            onChange={(e) => setShowAdvanced.mutate(e.target.checked)}
            disabled={setShowAdvanced.isPending}
          />
          Show Advanced section in navigation
        </label>
      )}

      <DesktopShortcut />

      <div className="flex gap-2">
        <Button size="sm" to="/plugins">
          Plugins
        </Button>
        <Button size="sm" to="/terminal">
          Terminal
        </Button>
      </div>
    </div>
  )
}
