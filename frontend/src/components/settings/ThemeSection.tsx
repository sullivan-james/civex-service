import { SegmentedControl } from '../ui'
import { useTheme, type ThemePreference } from '../../hooks/useTheme'

const options: { value: ThemePreference; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
]

export default function ThemeSection() {
  const { preference, setPreference } = useTheme()

  return (
    <SegmentedControl
      label="Theme"
      options={options}
      value={preference}
      onChange={setPreference}
    />
  )
}
