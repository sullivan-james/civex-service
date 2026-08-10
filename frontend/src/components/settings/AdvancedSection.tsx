import { useId } from 'react'
import { Link } from 'react-router'
import { useUISettings, useSetShowAdvanced } from '../../hooks/useUISettings'
import { Checkbox, Skeleton } from '../ui'

export default function AdvancedSection() {
  const { data: settings, isLoading } = useUISettings()
  const setShowAdvanced = useSetShowAdvanced()
  const checkboxId = useId()

  return (
    <div className="space-y-3">
      <div>
        <h2 className="text-lg font-semibold text-fg">Advanced</h2>
        <p className="text-sm text-fg-muted mt-0.5">
          Power-user surfaces — the terminal, raw YAML workflow editing, and the
          plugin editors. Not needed for everyday record and schema work.
        </p>
      </div>

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

      <p className="text-sm text-fg-muted">
        Always reachable here, whether or not the toggle above is on:{' '}
        <Link to="/plugins" className="text-accent hover:underline">
          Plugins
        </Link>{' '}
        ·{' '}
        <Link to="/terminal" className="text-accent hover:underline">
          Terminal
        </Link>
      </p>
    </div>
  )
}
