import { useState } from 'react'
import {
  useVolumes,
  useAddVolume,
  useUpdateVolume,
  useAdoptVolume,
  useRemoveVolume,
  useSetQueue,
} from '../../hooks/useStore'
import type { VolumeStats } from '../../api/store'
import {
  Button,
  Field,
  IconButton,
  Input,
  Checkbox,
  Skeleton,
  ErrorState,
} from '../ui'
import {
  AlertTriangle,
  ChevronUp,
  ChevronDown,
  X,
  Pencil,
  ArrowRight,
} from '../ui/icons'
import { errorMessage } from '../../lib/errors'
import GCPanel from './GCPanel'
import { PlacementPanel } from './PlacementPanel'

const STATE_LABEL: Record<VolumeStats['state'], string> = {
  online: 'online',
  offline: 'offline',
  wrong_drive: 'wrong drive',
  readonly: 'read-only',
  retired: 'retired',
}

const isDesktop = typeof window !== 'undefined' && !!window.pywebview

function normalizePath(p: string): string {
  return p.replace(/\\/g, '/')
}

async function browseFolderDesktop(): Promise<string | null> {
  if (!window.pywebview) return null
  const r = await window.pywebview.api.browse_folder()
  return r.path ?? null
}

const inputCls = 'w-full'

function fmtBytes(b: number | null): string {
  if (b === null) return '—'
  if (b >= 1_073_741_824) return `${(b / 1_073_741_824).toFixed(1)} GB`
  if (b >= 1_048_576) return `${(b / 1_048_576).toFixed(0)} MB`
  return `${(b / 1024).toFixed(0)} KB`
}

function UsageBar({
  used,
  total,
  warn,
}: {
  used: number | null
  total: number
  warn: boolean
}) {
  if (used === null)
    return <div className="h-1.5 w-full bg-border-muted rounded-full" />
  const pct = Math.min(100, (used / total) * 100)
  const color = warn
    ? 'bg-danger'
    : pct > 75
      ? 'bg-attention-muted'
      : 'bg-success'
  return (
    <div className="h-1.5 w-full bg-border-muted rounded-full overflow-hidden">
      <div
        className={`h-full rounded-full transition-all ${color}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

function VolumeCard({
  vol,
  queueIndex,
  queueLength,
  onMoveUp,
  onMoveDown,
  onRemoveFromQueue,
  onAddToQueue,
}: {
  vol: VolumeStats
  queueIndex: number
  queueLength: number
  onMoveUp: () => void
  onMoveDown: () => void
  onRemoveFromQueue: () => void
  onAddToQueue: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [confirmRemove, setConfirmRemove] = useState(false)
  const [editPath, setEditPath] = useState(vol.path)
  const [editAlloc, setEditAlloc] = useState(
    vol.allocated_gb != null ? String(vol.allocated_gb) : '',
  )
  const [clearAlloc, setClearAlloc] = useState(false)
  const updateVolume = useUpdateVolume()
  const removeVolume = useRemoveVolume()
  const adoptVolume = useAdoptVolume()
  const [confirmAdopt, setConfirmAdopt] = useState(false)
  const [removeError, setRemoveError] = useState<string | null>(null)

  const allocBytes =
    vol.allocated_gb != null ? vol.allocated_gb * 1_073_741_824 : null
  const diskTotal = vol.disk_total_bytes

  function handleSave() {
    const body: Parameters<typeof updateVolume.mutate>[0]['body'] = {}
    if (editPath !== vol.path) body.path = editPath
    if (clearAlloc) body.clear_allocation = true
    else if (editAlloc !== '' && Number(editAlloc) !== vol.allocated_gb)
      body.allocated_gb = Number(editAlloc)
    updateVolume.mutate(
      { name: vol.name, body },
      { onSuccess: () => setEditing(false) },
    )
  }

  return (
    <div
      className={`border rounded-md ${vol.warning ? 'border-attention-muted' : 'border-border'} bg-canvas`}
    >
      <div className="px-4 py-3 flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-semibold text-sm text-fg">{vol.name}</span>
            {vol.in_queue && (
              <span className="text-xs font-medium px-2 py-1 rounded-full bg-success-subtle text-success border border-success-muted">
                queue #{queueIndex + 1}
              </span>
            )}
            {vol.state !== 'online' && (
              <span
                className={`text-xs font-medium px-2 py-1 rounded-full border ${
                  vol.state === 'wrong_drive'
                    ? 'bg-danger-subtle text-danger border-danger-muted'
                    : 'bg-border-muted text-fg-muted border-border'
                }`}
              >
                {STATE_LABEL[vol.state]}
              </span>
            )}
            {vol.warning && (
              <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full bg-attention-subtle text-attention border border-attention-muted">
                <AlertTriangle size={12} /> low space
              </span>
            )}
          </div>
          <p className="text-xs text-fg-muted font-mono truncate">{vol.path}</p>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          {vol.in_queue && (
            <>
              <IconButton
                icon={ChevronUp}
                aria-label="Move up in queue"
                variant="subtle"
                onClick={onMoveUp}
                disabled={queueIndex === 0}
              />
              <IconButton
                icon={ChevronDown}
                aria-label="Move down in queue"
                variant="subtle"
                onClick={onMoveDown}
                disabled={queueIndex === queueLength - 1}
              />
              <button
                onClick={onRemoveFromQueue}
                className="inline-flex items-center gap-1 text-xs px-2 py-2 rounded-md text-fg-muted hover:text-danger hover:bg-canvas-subtle"
                title="Remove from write queue"
              >
                <X size={12} /> queue
              </button>
            </>
          )}
          {!vol.in_queue && (
            <button
              onClick={onAddToQueue}
              className="text-xs px-2 py-2 rounded-md border border-border text-fg-muted hover:bg-canvas-subtle"
              title="Add to write queue"
            >
              + queue
            </button>
          )}
          <IconButton
            icon={Pencil}
            aria-label="Edit volume"
            variant="default"
            className="hover:!text-accent"
            onClick={() => {
              setEditing((e) => !e)
              setConfirmRemove(false)
            }}
          />
          {confirmRemove ? (
            <>
              <button
                onClick={() => {
                  setRemoveError(null)
                  removeVolume.mutate(vol.name, {
                    onError: (e) =>
                      setRemoveError(
                        e instanceof Error ? e.message : String(e),
                      ),
                    onSuccess: () => setConfirmRemove(false),
                  })
                }}
                disabled={removeVolume.isPending}
                className="text-xs px-2 py-2 rounded-md bg-danger text-fg-on-emphasis hover:bg-danger-emphasis disabled:opacity-50"
              >
                Confirm
              </button>
              <button
                onClick={() => {
                  setConfirmRemove(false)
                  setRemoveError(null)
                }}
                className="text-xs px-2 py-2 text-fg-muted hover:underline"
              >
                Cancel
              </button>
            </>
          ) : (
            <IconButton
              icon={X}
              aria-label="Delete volume from config (does not delete files)"
              variant="danger"
              onClick={() => {
                setConfirmRemove(true)
                setEditing(false)
                setRemoveError(null)
              }}
            />
          )}
        </div>
      </div>

      {removeError && (
        <div className="px-4 pb-3">
          <p
            role="alert"
            className="text-xs text-danger bg-danger-subtle border border-danger-muted rounded-md px-3 py-2"
          >
            {removeError}
          </p>
        </div>
      )}

      {(vol.state === 'offline' || vol.state === 'wrong_drive') && (
        <div className="px-4 pb-3">
          <div className="text-xs bg-attention-subtle border border-attention-muted rounded-md px-3 py-2 space-y-1">
            <p className="text-fg">{vol.reason}</p>
            {vol.fix && <p className="text-fg-muted">{vol.fix}</p>}
            {vol.state === 'wrong_drive' &&
              (confirmAdopt ? (
                <div className="flex items-center gap-2 pt-1">
                  <span className="text-fg">
                    Treat the drive at this path as {vol.name}?
                  </span>
                  <button
                    onClick={() =>
                      adoptVolume.mutate(vol.name, {
                        onSuccess: () => setConfirmAdopt(false),
                      })
                    }
                    disabled={adoptVolume.isPending}
                    className="px-2 py-1 rounded-md bg-accent-emphasis text-fg-on-emphasis disabled:opacity-50"
                  >
                    Confirm
                  </button>
                  <button
                    onClick={() => setConfirmAdopt(false)}
                    className="px-2 py-1 text-fg-muted hover:underline"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setConfirmAdopt(true)}
                  className="pt-1 text-accent hover:underline"
                >
                  This is the right drive
                </button>
              ))}
            {adoptVolume.isError && (
              <p role="alert" className="text-danger">
                {errorMessage(adoptVolume.error)}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Usage bars */}
      {vol.available && (
        <div className="px-4 pb-3 space-y-2">
          {allocBytes !== null && (
            <div>
              <div className="flex justify-between text-xs text-fg-muted mb-1">
                <span>Civex usage</span>
                <span>
                  {fmtBytes(vol.civex_used_bytes)} / {fmtBytes(allocBytes)}
                </span>
              </div>
              <UsageBar
                used={vol.civex_used_bytes}
                total={allocBytes}
                warn={vol.warning}
              />
            </div>
          )}
          {diskTotal !== null && (
            <div>
              <div className="flex justify-between text-xs text-fg-muted mb-1">
                <span>Disk free</span>
                <span>
                  {fmtBytes(vol.disk_free_bytes)} of {fmtBytes(diskTotal)}
                </span>
              </div>
              <UsageBar
                used={diskTotal - (vol.disk_free_bytes ?? 0)}
                total={diskTotal}
                warn={!!(vol.disk_free_bytes !== null && vol.warning)}
              />
            </div>
          )}
        </div>
      )}

      {/* Inline editor */}
      {editing && (
        <div className="border-t border-border px-4 py-3 bg-canvas-subtle space-y-2 rounded-b-md">
          <div className="flex items-end gap-2">
            <Field label="Path" className="flex-1">
              <Input
                value={editPath}
                onChange={(e) => setEditPath(normalizePath(e.target.value))}
                onBlur={(e) => setEditPath(normalizePath(e.target.value))}
                className={inputCls}
              />
            </Field>
            {isDesktop && (
              <Button
                size="sm"
                onClick={async () => {
                  const p = await browseFolderDesktop()
                  if (p) setEditPath(p)
                }}
              >
                Browse…
              </Button>
            )}
          </div>
          <div className="flex items-end gap-2">
            <Field label="Allocation (GB)" className="flex-1">
              <Input
                type="number"
                min="0.1"
                step="0.1"
                value={clearAlloc ? '' : editAlloc}
                onChange={(e) => {
                  setEditAlloc(e.target.value)
                  setClearAlloc(false)
                }}
                placeholder="unlimited"
                className={inputCls}
                disabled={clearAlloc}
              />
            </Field>
            <Field
              label="Unlimited"
              layout="inline"
              className="text-xs text-fg-muted whitespace-nowrap"
            >
              <Checkbox
                checked={clearAlloc}
                onChange={(e) => setClearAlloc(e.target.checked)}
              />
            </Field>
          </div>
          {updateVolume.error && (
            <p role="alert" className="text-xs text-danger">
              {errorMessage(updateVolume.error)}
            </p>
          )}
          <div className="flex gap-2">
            <Button
              variant="primary"
              size="sm"
              onClick={handleSave}
              disabled={updateVolume.isPending}
            >
              {updateVolume.isPending ? 'Saving…' : 'Save'}
            </Button>
            <Button size="sm" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

function AddVolumeForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState('')
  const [path, setPath] = useState('')
  const [allocStr, setAllocStr] = useState('')
  const addVolume = useAddVolume()

  function handleAdd() {
    if (!name.trim() || !path.trim()) return
    addVolume.mutate(
      {
        name: name.trim(),
        path: path.trim(),
        allocated_gb: allocStr ? Number(allocStr) : null,
      },
      { onSuccess: onDone },
    )
  }

  return (
    <div className="border border-dashed border-accent-muted rounded-md p-4 bg-canvas-subtle space-y-3">
      <p className="text-xs font-semibold text-accent uppercase tracking-wide">
        New volume
      </p>
      <div className="grid grid-cols-3 gap-3">
        <Field label="Name" hint="letters, digits, - _" required>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. external"
            autoFocus
            className={inputCls}
          />
        </Field>
        <div className="flex items-end gap-2">
          <Field label="Path" className="flex-1" required>
            <Input
              value={path}
              onChange={(e) => setPath(normalizePath(e.target.value))}
              onBlur={(e) => setPath(normalizePath(e.target.value))}
              placeholder="/media/WD-8TB/civex-objects"
              className={inputCls}
            />
          </Field>
          {isDesktop && (
            <Button
              size="sm"
              onClick={async () => {
                const p = await browseFolderDesktop()
                if (p) setPath(p)
              }}
            >
              Browse…
            </Button>
          )}
        </div>
        <Field label="Allocation (GB, optional)">
          <Input
            type="number"
            min="0.1"
            step="0.1"
            value={allocStr}
            onChange={(e) => setAllocStr(e.target.value)}
            placeholder="unlimited"
            className={inputCls}
          />
        </Field>
      </div>
      {addVolume.error && (
        <p role="alert" className="text-xs text-danger">
          {errorMessage(addVolume.error)}
        </p>
      )}
      <div className="flex gap-2">
        <Button
          variant="primary"
          size="sm"
          onClick={handleAdd}
          disabled={addVolume.isPending || !name.trim() || !path.trim()}
        >
          {addVolume.isPending ? 'Adding…' : 'Add volume'}
        </Button>
        <Button size="sm" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

export default function StorageSection() {
  const { data: volumes, isLoading, error } = useVolumes()
  const setQueue = useSetQueue()
  const [addingVolume, setAddingVolume] = useState(false)

  if (isLoading)
    return (
      <div className="space-y-6" aria-hidden="true">
        <div className="flex items-center justify-between">
          <div className="space-y-2">
            <Skeleton className="h-5 w-20" />
            <Skeleton className="h-4 w-96" />
          </div>
          <Skeleton className="h-8 w-28" />
        </div>
        <div className="space-y-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      </div>
    )
  if (error || !volumes)
    return (
      <ErrorState
        message={error ? errorMessage(error) : 'Failed to load volumes'}
      />
    )

  const queue = volumes
    .filter((v) => v.in_queue)
    .sort((a, b) => {
      const qi = volumes.filter((v) => v.in_queue).map((v) => v.name)
      return qi.indexOf(a.name) - qi.indexOf(b.name)
    })
  const queueNames = queue.map((v) => v.name)

  function moveInQueue(name: string, dir: -1 | 1) {
    const idx = queueNames.indexOf(name)
    const next = [...queueNames]
    const swap = idx + dir
    ;[next[idx], next[swap]] = [next[swap], next[idx]]
    setQueue.mutate(next)
  }

  function removeFromQueue(name: string) {
    setQueue.mutate(queueNames.filter((n) => n !== name))
  }

  function addToQueue(name: string) {
    setQueue.mutate([...queueNames, name])
  }

  const hasWarning = volumes.some((v) => v.warning)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-fg">Storage</h2>
          <p className="text-sm text-fg-muted mt-1">
            Configure where civex stores files. New uploads go to the first
            available volume in the write queue.
          </p>
        </div>
        {!addingVolume && (
          <Button size="sm" onClick={() => setAddingVolume(true)}>
            + Add volume
          </Button>
        )}
      </div>

      {hasWarning && (
        <div className="flex items-start gap-1.5 border border-attention-muted rounded-md px-4 py-3 bg-attention-subtle text-sm text-attention">
          <AlertTriangle size={14} className="shrink-0 mt-0.5" />
          One or more volumes are running low on space. Consider adding a new
          volume or freeing disk space.
        </div>
      )}

      {addingVolume && <AddVolumeForm onDone={() => setAddingVolume(false)} />}

      <div className="space-y-3">
        {volumes.length === 0 && (
          <p className="text-sm text-fg-muted italic">No volumes configured.</p>
        )}
        {volumes.map((vol) => {
          const qi = queueNames.indexOf(vol.name)
          return (
            <VolumeCard
              key={vol.name}
              vol={vol}
              queueIndex={qi}
              queueLength={queueNames.length}
              onMoveUp={() => moveInQueue(vol.name, -1)}
              onMoveDown={() => moveInQueue(vol.name, 1)}
              onRemoveFromQueue={() => removeFromQueue(vol.name)}
              onAddToQueue={() => addToQueue(vol.name)}
            />
          )
        })}
      </div>

      <div className="border border-border rounded-md px-4 py-3 bg-canvas-subtle text-xs text-fg-muted space-y-1">
        <p className="flex items-center flex-wrap gap-1">
          <span className="font-semibold text-fg">Write queue:</span>
          {queueNames.length ? (
            queueNames.map((name, i) => (
              <span key={name} className="inline-flex items-center gap-1">
                {i > 0 && <ArrowRight size={11} />}
                {name}
              </span>
            ))
          ) : (
            <span>empty</span>
          )}
        </p>
        <p>
          Civex tries each volume in order. A volume is skipped if its
          allocation is full or disk space is below the headroom threshold.
        </p>
      </div>

      <PlacementPanel />

      <GCPanel />
    </div>
  )
}
