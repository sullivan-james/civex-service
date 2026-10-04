import { useState } from 'react'
import type { Transfer } from '../../../api/transfers'
import {
  useCancelTransfer,
  usePauseTransfer,
  useResumeTransfer,
  useTransfers,
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
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Skeleton,
} from '../../ui'
import { TransferCard } from './TransferCard'
import { NewTransferModal, type TransferPreset } from './NewTransferModal'

/** Moving files between volumes: start a move, and watch, pause or cancel it. */
export function TransfersTab({ preset }: { preset?: TransferPreset }) {
  const { data, isLoading, error } = useTransfers()
  const [creating, setCreating] = useState<TransferPreset | null>(
    preset ?? null,
  )

  if (isLoading) return <Skeleton className="h-24 w-full" />
  if (error) return <ErrorState message={errorMessage(error)} />

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-fg-muted">
          Empty a volume, or gather a collection onto one. Every file is checked
          before the original is removed, so a move can be paused or stopped at
          any time.
        </p>
        <Button variant="primary" onClick={() => setCreating({})}>
          Move files…
        </Button>
      </div>
      {data && data.length > 0 ? (
        <ul className="space-y-3">
          {data.map((t) => (
            <TransferCard key={t.id} t={t} />
          ))}
        </ul>
      ) : (
        <EmptyState
          title="No moves yet"
          message="Moves you start appear here."
        />
      )}
      {creating && (
        <NewTransferModal preset={creating} onClose={() => setCreating(null)} />
      )}
    </div>
  )
}
