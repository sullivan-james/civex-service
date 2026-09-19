import { useState } from 'react'
import { useRunGC } from '../../hooks/useStore'
import type { GCReport } from '../../api/store'
import { Button, Field, Input, ConfirmDialog } from '../ui'
import { errorMessage } from '../../lib/errors'

function fmtBytes(b: number): string {
  if (b >= 1_073_741_824) return `${(b / 1_073_741_824).toFixed(1)} GB`
  if (b >= 1_048_576) return `${(b / 1_048_576).toFixed(1)} MB`
  if (b >= 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${b} B`
}

export default function GCPanel() {
  const [graceDays, setGraceDays] = useState('14')
  const [report, setReport] = useState<GCReport | null>(null)
  const [confirming, setConfirming] = useState(false)
  const runGC = useRunGC()

  const days = Number(graceDays) || 0

  function preview() {
    setReport(null)
    runGC.mutate({ apply: false, grace_days: days }, { onSuccess: setReport })
  }

  function apply() {
    runGC.mutate(
      { apply: true, grace_days: days },
      {
        onSuccess: (r) => {
          setReport(r)
          setConfirming(false)
        },
      },
    )
  }

  return (
    <div className="space-y-3">
      <div>
        <h2 className="text-lg font-semibold text-fg">Garbage collection</h2>
        <p className="text-sm text-fg-muted mt-1">
          Reclaims stored files no longer referenced by any record or workflow
          run. Files only referenced by old audit history are not protected — an
          old audit diff may point at a file GC has since removed.
        </p>
      </div>

      <div className="flex items-end gap-3">
        <Field
          label="Grace period (days)"
          hint="Unreferenced files newer than this are left alone"
        >
          <Input
            type="number"
            min="0"
            step="1"
            value={graceDays}
            onChange={(e) => setGraceDays(e.target.value)}
            className="w-40"
          />
        </Field>
        <Button size="sm" onClick={preview} disabled={runGC.isPending}>
          {runGC.isPending && !confirming ? 'Scanning…' : 'Preview'}
        </Button>
      </div>

      {runGC.error && !confirming && (
        <p role="alert" className="text-xs text-danger">
          {errorMessage(runGC.error)}
        </p>
      )}

      {report &&
        (() => {
          const hasCollectible =
            report.deleted_count > 0 || report.stale_scratch_removed > 0
          const verb = report.dry_run ? 'collectible' : 'reclaimed'
          return (
            <div className="border border-border rounded-md px-4 py-3 bg-canvas-subtle text-sm space-y-2">
              <p className="text-fg-muted">
                Scanned{' '}
                <span className="font-medium text-fg">{report.scanned}</span>{' '}
                object(s) — {report.referenced} referenced,{' '}
                {report.protected_by_grace} within the grace period.
              </p>
              {!hasCollectible ? (
                <p className="text-fg-muted">Nothing to reclaim.</p>
              ) : report.dry_run ? (
                <div className="flex items-center justify-between gap-3">
                  <p>
                    <span className="font-semibold text-fg">
                      {report.deleted_count} object(s)
                    </span>{' '}
                    ({fmtBytes(report.deleted_bytes)})
                    {report.stale_scratch_removed > 0 &&
                      ` + ${report.stale_scratch_removed} abandoned upload(s)`}{' '}
                    {verb}.
                  </p>
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={() => setConfirming(true)}
                  >
                    Delete…
                  </Button>
                </div>
              ) : (
                <p className="text-success">
                  Reclaimed {report.deleted_count} object(s) (
                  {fmtBytes(report.deleted_bytes)})
                  {report.stale_scratch_removed > 0 &&
                    ` + ${report.stale_scratch_removed} abandoned upload(s)`}
                  .
                </p>
              )}
            </div>
          )
        })()}

      {confirming && report && (
        <ConfirmDialog
          title="Delete unreferenced files?"
          body={
            <>
              This permanently deletes{' '}
              <span className="font-semibold">
                {report.deleted_count} object(s)
              </span>{' '}
              ({fmtBytes(report.deleted_bytes)})
              {report.stale_scratch_removed > 0 &&
                ` and ${report.stale_scratch_removed} abandoned upload scratch file(s)`}{' '}
              from the object store. This cannot be undone.
            </>
          }
          confirmLabel="Delete"
          variant="danger"
          isPending={runGC.isPending}
          onConfirm={apply}
          onClose={() => setConfirming(false)}
          warning={runGC.error ? errorMessage(runGC.error) : undefined}
        />
      )}
    </div>
  )
}
