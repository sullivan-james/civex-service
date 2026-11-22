import { useState, type ReactNode } from 'react'
import { useHasFeature } from '../../hooks/useFeatures'
import { useStored } from '../../hooks/useStored'
import { EXPORT_FOLDER_KEY } from '../../utils/exportFolder'
import { FolderPickerModal } from '../settings/FolderPickerModal'
import { Button, CheckRow } from '../ui'
import { Archive, FolderOpen } from '../ui/icons'

import type { ExportMethod } from '../../api/exportDefinitions'

export type Method = ExportMethod

/** How an export is handed over: **Save to a folder**, or **Download a zip**.
 * A folder is any folder of this computer, chosen with the folder browser and
 * remembered (none chosen: civex's own exports folder). How the folder is
 * made is civex's business: links to the stored files where that is possible
 * there (instant, no extra space, read-only) and copies where it is not;
 * **Make copies I can edit** asks for copies throughout. Those two are the
 * stored methods `link` and `copy`; a table alone is always a copy. */
export function MethodStep({
  files = true,
  method,
  setMethod,
  zip = true,
}: {
  /** False for a table alone: there are no files to link to or zip. */
  files?: boolean
  method: Method
  setMethod: (m: Method) => void
  /** False where a zip isn't offered (too big to download). */
  zip?: boolean
  /** Kept for callers that still pass a drive: a saved export may name one,
   * and runs on it when no folder is chosen. */
  drive?: string | null
  setDrive?: (d: string) => void
  need?: number
}) {
  const has = useHasFeature()
  const [folder, setFolder] = useStored<string | null>(EXPORT_FOLDER_KEY, null)
  const [browsing, setBrowsing] = useState(false)
  // A folder is made on this machine; a server keeping its files in a bucket
  // offers the zip alone.
  const folders = has('volumes')
  const toFolder = method !== 'zip'
  return (
    <div role="radiogroup" aria-label="Method" className="space-y-3">
      {folders && (
        <MethodCard
          selected={toFolder}
          onSelect={() => setMethod(files ? 'link' : 'copy')}
          icon={<FolderOpen size={22} aria-hidden="true" />}
          title="Save to a folder"
          hint="Opens when it is ready"
        >
          {toFolder && (
            <div className="mt-3 max-w-md space-y-2 text-sm">
              <div className="flex items-center gap-2">
                <span
                  className="min-w-0 flex-1 truncate font-mono text-xs"
                  title={folder ?? undefined}
                >
                  {folder ?? 'civex’s exports folder'}
                </span>
                <Button size="sm" onClick={() => setBrowsing(true)}>
                  Choose…
                </Button>
                {folder && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setFolder(null)}
                  >
                    Reset
                  </Button>
                )}
              </div>
              {files && (
                <CheckRow
                  compact
                  checked={method === 'copy'}
                  onChange={(on) => setMethod(on ? 'copy' : 'link')}
                  title="Make copies I can edit"
                />
              )}
            </div>
          )}
        </MethodCard>
      )}
      {zip && (
        <MethodCard
          selected={method === 'zip'}
          onSelect={() => setMethod('zip')}
          icon={<Archive size={22} aria-hidden="true" />}
          title={files ? 'Download a zip' : 'Download'}
          hint="One file, to send"
        />
      )}
      {browsing && (
        <FolderPickerModal
          initialPath={folder ?? undefined}
          onSelect={setFolder}
          onClose={() => setBrowsing(false)}
        />
      )}
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
