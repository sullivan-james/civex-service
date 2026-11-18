import type { ReactNode } from 'react'
import { useDriveChoice } from '../../hooks/useDriveChoice'
import { useHasFeature } from '../../hooks/useFeatures'
import { DrivePicker } from '../files/DrivePicker'
import { Archive, FolderOpen, HardDrive } from '../ui/icons'

import type { ExportMethod } from '../../api/exportDefinitions'

export type Method = ExportMethod

const METHODS: {
  id: Method
  title: string
  hint: string
  icon: typeof FolderOpen
}[] = [
  {
    id: 'link',
    title: 'Open as a folder',
    hint: 'Ready at once, taking almost no space. To change the files, edit them in civex or put them on a drive.',
    icon: FolderOpen,
  },
  {
    id: 'copy',
    title: 'Put on a drive',
    hint: 'Files of your own to change or take away, such as on a USB stick.',
    icon: HardDrive,
  },
  {
    id: 'zip',
    title: 'Download as a zip',
    hint: 'One file, to send or keep somewhere else.',
    icon: Archive,
  },
]

/** The same choices in words for a table with no files. */
const TABLE_ONLY: Partial<Record<Method, { title: string; hint: string }>> = {
  copy: { title: 'Save to a drive', hint: 'A folder holding the table.' },
  zip: { title: 'Download', hint: 'The table, as one file.' },
}

/** What the person ends up with: a folder to open, files on a drive, or a zip.
 * How a folder is made (links to the stored files, copies of any that can't be
 * linked) is civex's business, never a choice. A drive also asks which, with
 * its free space. */
export function MethodStep({
  files = true,
  method,
  setMethod,
  drive,
  setDrive,
  need = 0,
}: {
  /** False for a table alone: there are no files to link to or zip. */
  files?: boolean
  method: Method
  setMethod: (m: Method) => void
  drive: string | null
  setDrive: (d: string) => void
  /** Bytes the files take, when known: whether they fit on the drive. */
  need?: number
}) {
  const choice = useDriveChoice({ need, allowProject: true, chosen: drive })
  const has = useHasFeature()
  // A folder of links or copies is made on a drive of this machine; a server
  // keeping its files in a bucket offers the zip alone.
  const offered = METHODS.filter(
    (m) => (m.id === 'zip' || has('volumes')) && (files || m.id !== 'link'),
  )
  return (
    <div role="radiogroup" aria-label="Method" className="space-y-3">
      {offered.map((m) => (
        <MethodCard
          key={m.id}
          selected={method === m.id}
          onSelect={() => setMethod(m.id)}
          icon={<m.icon size={22} aria-hidden="true" />}
          title={files ? m.title : (TABLE_ONLY[m.id]?.title ?? m.title)}
          hint={files ? m.hint : (TABLE_ONLY[m.id]?.hint ?? m.hint)}
        >
          {m.id === 'copy' && method === 'copy' && (
            <div className="mt-3 max-w-md space-y-1 text-sm">
              <DrivePicker
                label="Which drive"
                value={choice.target}
                targets={choice.targets}
                allowProject
                need={need}
                free={choice.free}
                tooBig={choice.tooBig}
                onChange={setDrive}
              />
            </div>
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
  // The card's settings (the drive) sit below its label, not inside it: a
  // label can't hold another control's label.
  return (
    <div
      className={`rounded-lg border p-4 transition-colors ${
        selected
          ? 'border-accent bg-accent-subtle ring-1 ring-accent'
          : 'border-border hover:bg-canvas-subtle'
      }`}
    >
      <label className="flex cursor-pointer items-start gap-4">
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
        </span>
      </label>
      {children && <div className="pl-[4.25rem]">{children}</div>}
    </div>
  )
}
