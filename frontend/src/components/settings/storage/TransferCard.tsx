import { useState } from 'react'
import type { Transfer } from '../../../api/transfers'
import {
  useCancelTransfer,
  usePauseTransfer,
  useResumeTransfer,
} from '../../../hooks/useTransfers'
import { errorMessage } from '../../../lib/errors'
import { formatEstimate } from '../../../utils/dbFormat'
import { formatSize } from '../../../utils/storage'
import {
  RESUMABLE,
  STATUS_LABEL,
  STATUS_VARIANT,
  percentDone,
} from '../../../utils/transfers'
import { Badge, Button, ConfirmDialog } from '../../ui'

export function describeTransfer(t: Transfer): string {
  return t.kind === 'drain'
    ? `Empty ${t.spec.sources.join(', ')} onto ${t.spec.targets.join(', ')}`
    : `Gather ${t.spec.collection_ids.length} collection(s) onto ${t.spec.targets.join(', ')}`
}

export function TransferCard({ t }: { t: Transfer }) {
  const pause = usePauseTransfer()
  const resume = useResumeTransfer()
  const cancel = useCancelTransfer()
  const [confirming, setConfirming] = useState(false)
  const p = t.progress
  const pct = percentDone(p)
  const active = t.status === 'running'
  const error = [pause, resume, cancel].find((m) => m.isError)?.error

  return (
    <li className="rounded-md border border-border bg-canvas-subtle p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-medium text-fg">{describeTransfer(t)}</p>
          <p className="text-xs text-fg-muted">
            {p.files_done} of {p.files_total} files · {formatSize(p.bytes_done)}{' '}
            of {formatSize(p.bytes_total)}
          </p>
        </div>
        <Badge variant={STATUS_VARIANT[t.status]}>
          {t.control && active
            ? `${t.control === 'pause' ? 'Pausing' : 'Cancelling'}…`
            : STATUS_LABEL[t.status]}
        </Badge>
      </div>

      {(active || t.status === 'paused') && (
        <div
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Progress"
          className="mt-3 h-2 overflow-hidden rounded-full bg-canvas-inset"
        >
          <div
            className="h-full bg-accent transition-[width]"
            style={{ width: `${pct}%` }}
          />
        </div>
      )}

      {active && (
        <p className="mt-1 text-xs text-fg-muted">
          {formatSize(p.rate_bytes_per_second)}/s · about{' '}
          {p.eta_seconds == null
            ? 'time left unknown'
            : `${formatEstimate(p.eta_seconds)} left`}
        </p>
      )}
      {t.pause_reason && (
        <p className="mt-2 text-sm text-attention">
          {t.pause_reason}
          {t.auto_resume && ' It will carry on by itself when that is fixed.'}
        </p>
      )}
      {t.error && <p className="mt-2 text-sm text-danger">{t.error}</p>}
      {t.status === 'interrupted' && (
        <p className="mt-2 text-sm text-attention">
          Civex stopped while this was running. Nothing was lost; resume to
          carry on.
        </p>
      )}
      {t.failures_total > 0 && (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer text-danger">
            {t.failures_total} file(s) could not be moved and stay where they
            were
          </summary>
          <ul className="mt-1 space-y-0.5 text-xs text-fg-muted">
            {t.failures.map((f) => (
              <li key={f.sha256}>
                <span className="font-mono">{f.sha256.slice(0, 12)}</span> on{' '}
                {f.volume}: {f.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
      {error && (
        <p className="mt-2 text-sm text-danger">{errorMessage(error)}</p>
      )}

      <div className="mt-3 flex gap-2">
        {active && (
          <Button
            size="sm"
            disabled={pause.isPending || !!t.control}
            onClick={() => pause.mutate(t.id)}
          >
            Pause
          </Button>
        )}
        {RESUMABLE.includes(t.status) && (
          <Button
            size="sm"
            variant="primary"
            disabled={resume.isPending}
            onClick={() => resume.mutate(t.id)}
          >
            Resume
          </Button>
        )}
        {(active || RESUMABLE.includes(t.status)) && (
          <Button
            size="sm"
            variant="danger"
            onClick={() => setConfirming(true)}
          >
            Cancel
          </Button>
        )}
      </div>

      {confirming && (
        <ConfirmDialog
          title="Cancel this transfer?"
          confirmLabel="Cancel transfer"
          variant="danger"
          isPending={cancel.isPending}
          body={
            <p className="text-sm">
              Files already moved stay where they are, and nothing is lost.
              Volumes made read-only for the move are put back as they were.
            </p>
          }
          onConfirm={() =>
            cancel.mutate(t.id, { onSuccess: () => setConfirming(false) })
          }
          onClose={() => setConfirming(false)}
        />
      )}
    </li>
  )
}
