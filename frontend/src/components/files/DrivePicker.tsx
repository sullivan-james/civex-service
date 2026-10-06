import { formatSize } from '../../utils/storage'
import { Select } from '../ui'
import { PROJECT } from '../../hooks/useDriveChoice'

export function DrivePicker({
  label,
  value,
  targets,
  allowProject,
  need,
  free,
  tooBig,
  disabled,
  onChange,
}: {
  label: string
  value: string
  targets: { name: string; disk_free_bytes: number | null }[]
  allowProject: boolean
  need: number
  free: number | null
  tooBig: boolean
  disabled?: boolean
  onChange: (volume: string) => void
}) {
  return (
    <>
      <label className="block">
        <span className="mb-1 block font-medium text-fg">{label}</span>
        <Select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
        >
          {allowProject && <option value={PROJECT}>The project folder</option>}
          {targets.map((v) => (
            <option key={v.name} value={v.name}>
              {v.name}
              {v.disk_free_bytes != null
                ? ` — ${formatSize(v.disk_free_bytes)} free`
                : ''}
            </option>
          ))}
        </Select>
      </label>
      {tooBig && (
        <p role="alert" className="text-danger">
          Not enough room: this needs {formatSize(need)} and “{value}” has{' '}
          {formatSize(free)} free.
        </p>
      )}
    </>
  )
}
