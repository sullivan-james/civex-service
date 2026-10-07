import { SegmentedControl } from '../ui'
import { useTheme, type ThemePreference } from '../../hooks/useTheme'
import {
  setUiSize,
  UI_SIZES,
  useUiSize,
  type UiSize,
} from '../../hooks/useUiSize'

const options: { value: ThemePreference; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
]

const sizeOptions = UI_SIZES.map((size) => ({
  value: String(size),
  label: `${size}%`,
}))

export default function ThemeSection() {
  const { preference, setPreference } = useTheme()
  const size = useUiSize()

  return (
    <div className="space-y-5">
      <SegmentedControl
        label="Theme"
        options={options}
        value={preference}
        onChange={setPreference}
      />
      <SegmentedControl
        label="Size"
        options={sizeOptions}
        value={String(size)}
        onChange={(next) => setUiSize(Number(next) as UiSize)}
      />
    </div>
  )
}
