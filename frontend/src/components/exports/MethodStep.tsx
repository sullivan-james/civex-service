import type { ReactNode } from 'react'
import { PROJECT, useDriveChoice } from '../../hooks/useDriveChoice'
import { Select } from '../ui'
import { Archive, FolderOpen, HardDrive } from '../ui/icons'

export type Method = 'link' | 'copy' | 'zip'

const METHODS: {
  id: Method
  title: string
  hint: string
  icon: typeof FolderOpen
}[] = [
  {
    id: 'link',
    title: 'Open as folder',
    hint: 'Links to the files where they already are. Nothing is copied.',
    icon: FolderOpen,
  },
  {
    id: 'copy',
    title: 'Copy to a drive',
    hint: 'Real copies you can edit.',
    icon: HardDrive,
  },
  {
    id: 'zip',
    title: 'Download zip',
    hint: 'One file, for another machine.',
    icon: Archive,
  },
]

/** The same choices in words for a table with no files. */
const TABLE_ONLY: Partial<Record<Method, { title: string; hint: string }>> = {
  copy: { title: 'Save to a drive', hint: 'A folder holding the table.' },
  zip: { title: 'Download', hint: 'The table, as one file.' },
}

/** How to get the files: three choices of the one export. Copying also asks which
 * drive. */
export function MethodStep({
  files = true,
  method,
  setMethod,
  drive,
  setDrive,
}: {
  /** False for a table alone: there are no files to link to or zip. */
  files?: boolean
  method: Method
  setMethod: (m: Method) => void
  drive: string | null
  setDrive: (d: string) => void
}) {
  const choice = useDriveChoice({ need: 0, allowProject: true, chosen: drive })
  return (
    <div role="radiogroup" aria-label="Method" className="space-y-3">
      {METHODS.filter((m) => files || m.id !== 'link').map((m) => (
        <MethodCard
          key={m.id}
          selected={method === m.id}
          onSelect={() => setMethod(m.id)}
          icon={<m.icon size={22} aria-hidden="true" />}
          title={files ? m.title : (TABLE_ONLY[m.id]?.title ?? m.title)}
          hint={files ? m.hint : (TABLE_ONLY[m.id]?.hint ?? m.hint)}
        >
          {m.id === 'copy' && method === 'copy' && (
            <Select
              size="lg"
              aria-label="Copy onto"
              className="mt-3 w-full max-w-md"
              value={choice.target}
              onChange={(e) => setDrive(e.target.value)}
            >
              <option value={PROJECT}>The project folder</option>
              {choice.targets.map((v) => (
                <option key={v.name} value={v.name}>
                  {v.name}
                </option>
              ))}
            </Select>
          )}
        </MethodCard>
      ))}
    </div>
  )
}

function MethodCard({
  selected,
  onSelect,
  icon,
  title,
  hint,
  children,
}: {
  selected: boolean
  onSelect: () => void
  icon: ReactNode
  title: string
  hint: string
  children?: ReactNode
}) {
  return (
    <label
      className={`flex cursor-pointer items-start gap-4 rounded-lg border p-4 transition-colors ${
        selected
          ? 'border-accent bg-accent-subtle ring-1 ring-accent'
          : 'border-border hover:bg-canvas-subtle'
      }`}
    >
      <input
        type="radio"
        name="method"
        className="mt-1"
        checked={selected}
        onChange={onSelect}
        aria-label={title}
      />
      <span className="mt-0.5 text-fg-muted">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-base font-medium text-fg">{title}</span>
        <span className="block text-sm text-fg-muted">{hint}</span>
        {children}
      </span>
    </label>
  )
}
