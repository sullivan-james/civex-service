import { useEffect, useRef, useState } from 'react'
import type { GCReport } from '../../../api/store'
import { useRunGC } from '../../../hooks/useStore'
import { errorMessage } from '../../../lib/errors'
import { formatSize } from '../../../utils/storage'
import {
  Button,
  Disclosure,
  Field,
  InfoTip,
  Input,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Spinner,
} from '../../ui'

const DEFAULT_GRACE_DAYS = 14

const plural = (n: number, one: string, many: string) =>
  `${n.toLocaleString()} ${n === 1 ? one : many}`

/** Free the space taken by stored files nothing uses, on one volume or all of
 * them. It looks first, on its own, and says what it found in plain words; one
 * button then deletes exactly that. Used from a volume's page (`volume` set)
 * and from Tasks (every volume), so the two can't disagree. */
export function CleanUpDialog({
  volume,
  onClose,
}: {
  volume?: string
  onClose: () => void
}) {
  const gc = useRunGC()
  const [graceDays, setGraceDays] = useState(String(DEFAULT_GRACE_DAYS))
  const [report, setReport] = useState<GCReport | null>(null)
  const [freed, setFreed] = useState<GCReport | null>(null)
  const started = useRef(false)

  const days = Math.max(0, Math.floor(Number(graceDays) || 0))
  const where = volume ? `on '${volume}'` : 'on any volume'

  function look() {
    setReport(null)
    setFreed(null)
    gc.mutate(
      { apply: false, grace_days: days, volume },
      { onSuccess: setReport },
    )
  }

  function deleteThem() {
    gc.mutate(
      { apply: true, grace_days: days, volume },
      {
        onSuccess: (r) => {
          setFreed(r)
          setReport(null)
        },
      },
    )
  }

  // Look as soon as it opens: there's nothing to decide before that.
  useEffect(() => {
    if (started.current) return
    started.current = true
    look()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const checking = gc.isPending && !gc.variables?.apply
  const deleting = gc.isPending && !!gc.variables?.apply
  const found =
    report !== null &&
    (report.deleted_count > 0 || report.stale_scratch_removed > 0)
  const byVolume = report ? sizeByVolume(report) : []

  return (
    <Modal onClose={onClose} size="md" dismissible={!deleting}>
      <ModalHeader onClose={onClose}>
        Clean up unused files{volume ? ` on ${volume}` : ''}
      </ModalHeader>
      <ModalBody>
        <div className="space-y-4 text-sm" aria-live="polite">
          {checking && (
            <p className="flex items-center gap-2 text-fg-muted">
              <Spinner /> Looking for files nothing uses…
            </p>
          )}

          {gc.isError && (
            <p role="alert" className="text-danger">
              {errorMessage(gc.error)}
            </p>
          )}

          {freed && (
            <p className="text-success" role="status">
              {freed.deleted_count > 0
                ? `Freed ${formatSize(freed.deleted_bytes)}: deleted ${plural(
                    freed.deleted_count,
                    'file',
                    'files',
                  )}.`
                : 'Nothing was left to delete.'}
            </p>
          )}

          {report && !found && (
            <p className="text-fg">
              Nothing to clean up {where}. Every file is used by a record or a
              workflow run
              {report.protected_by_grace > 0 &&
                `, or was added in the last ${days} ${days === 1 ? 'day' : 'days'} (${plural(report.protected_by_grace, 'file', 'files')})`}
              .
            </p>
          )}

          {report && found && (
            <div className="space-y-2">
              <p className="text-fg">
                <strong>
                  {plural(report.deleted_count, 'file', 'files')} (
                  {formatSize(report.deleted_bytes)})
                </strong>{' '}
                {where} {report.deleted_count === 1 ? 'is' : 'are'} not used by
                any record or workflow run.
                {report.stale_scratch_removed > 0 &&
                  ` Plus ${plural(report.stale_scratch_removed, 'abandoned upload', 'abandoned uploads')}.`}
              </p>
              {!volume && byVolume.length > 1 && (
                <ul className="text-fg-muted">
                  {byVolume.map((v) => (
                    <li key={v.volume}>
                      {v.volume}: {plural(v.files, 'file', 'files')} (
                      {formatSize(v.bytes)})
                    </li>
                  ))}
                </ul>
              )}
              <p className="text-fg-muted">
                Deleting them can&apos;t be undone. Files added in the last{' '}
                {days} {days === 1 ? 'day' : 'days'} are kept
                {report.protected_by_grace > 0 &&
                  ` (${plural(report.protected_by_grace, 'file', 'files')} so far)`}
                .
              </p>
            </div>
          )}

          <Disclosure summary={<span className="text-fg-muted">Options</span>}>
            <div className="flex items-end gap-3 p-3">
              <Field
                label="Keep files added in the last (days)"
                info="A file just uploaded may not be attached to its record yet, so recent files are left alone."
              >
                <Input
                  type="number"
                  min="0"
                  step="1"
                  value={graceDays}
                  onChange={(e) => setGraceDays(e.target.value)}
                  className="w-32"
                />
              </Field>
              <Button size="sm" onClick={look} disabled={gc.isPending}>
                Check again
              </Button>
            </div>
          </Disclosure>
          <p className="flex items-center gap-1 text-xs text-fg-subtle">
            Files that only old history refers to are not kept.
            <InfoTip>
              A file used only by an old audit entry or an old workflow log is
              treated as unused. That entry may then point at a file that is no
              longer there.
            </InfoTip>
          </p>
        </div>
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose} disabled={deleting}>
          {freed ? 'Done' : 'Close'}
        </Button>
        {found && report && (
          <Button variant="danger" disabled={gc.isPending} onClick={deleteThem}>
            {deleting
              ? 'Deleting…'
              : `Delete ${plural(report.deleted_count, 'file', 'files')} (${formatSize(report.deleted_bytes)})`}
          </Button>
        )}
      </ModalFooter>
    </Modal>
  )
}

function sizeByVolume(report: GCReport) {
  const totals = new Map<string, { files: number; bytes: number }>()
  for (const o of report.deleted) {
    const t = totals.get(o.volume) ?? { files: 0, bytes: 0 }
    t.files += 1
    t.bytes += o.size
    totals.set(o.volume, t)
  }
  return [...totals].map(([volume, t]) => ({ volume, ...t }))
}
