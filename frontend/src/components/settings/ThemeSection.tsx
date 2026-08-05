import { useTheme, type ThemePreference } from '../../hooks/useTheme'

const options: { value: ThemePreference; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
]

export default function ThemeSection() {
  const { preference, setPreference } = useTheme()

  return (
    <div className="space-y-3">
      <div>
        <h2 className="text-lg font-semibold text-fg">Appearance</h2>
        <p className="text-sm text-fg-muted mt-0.5">
          Choose how civex looks. System follows your OS setting.
        </p>
      </div>
      <div
        role="radiogroup"
        aria-label="Theme"
        className="inline-flex rounded-md border border-border overflow-hidden"
      >
        {options.map(({ value, label }, i) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={preference === value}
            onClick={() => setPreference(value)}
            className={`px-3 py-1.5 text-sm font-medium transition-colors ${
              i > 0 ? 'border-l border-border' : ''
            } ${
              preference === value
                ? 'bg-fg text-fg-on-emphasis'
                : 'bg-canvas text-fg-muted hover:bg-canvas-subtle'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  )
}
