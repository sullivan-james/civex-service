import { useState } from 'react'
import { useVolumes, useAddVolume, useUpdateVolume, useRemoveVolume, useSetQueue } from '../hooks/useStore'
import type { VolumeStats } from '../api/store'
import { Button, LoadingState, ErrorState } from '../components/ui'

const isDesktop = typeof window !== 'undefined' && !!window.pywebview

function normalizePath(p: string): string {
  return p.replace(/\\/g, '/')
}

async function browseFolderDesktop(): Promise<string | null> {
  if (!window.pywebview) return null
  const r = await window.pywebview.api.browse_folder()
  return r.path ?? null
}

const inputCls = 'border border-[#d0d7de] rounded-md px-3 py-1.5 text-sm bg-white focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da] w-full'

function fmtBytes(b: number | null): string {
  if (b === null) return '—'
  if (b >= 1_073_741_824) return `${(b / 1_073_741_824).toFixed(1)} GB`
  if (b >= 1_048_576) return `${(b / 1_048_576).toFixed(0)} MB`
  return `${(b / 1024).toFixed(0)} KB`
}

function UsageBar({ used, total, warn }: { used: number | null; total: number; warn: boolean }) {
  if (used === null) return <div className="h-1.5 w-full bg-[#eaeef2] rounded-full" />
  const pct = Math.min(100, (used / total) * 100)
  const color = warn ? 'bg-[#d1242f]' : pct > 75 ? 'bg-[#d4a72c]' : 'bg-[#1a7f37]'
  return (
    <div className="h-1.5 w-full bg-[#eaeef2] rounded-full overflow-hidden">
      <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
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
  const [editAlloc, setEditAlloc] = useState(vol.allocated_gb != null ? String(vol.allocated_gb) : '')
  const [clearAlloc, setClearAlloc] = useState(false)
  const updateVolume = useUpdateVolume()
  const removeVolume = useRemoveVolume()
  const [removeError, setRemoveError] = useState<string | null>(null)

  const allocBytes = vol.allocated_gb != null ? vol.allocated_gb * 1_073_741_824 : null
  const diskTotal = vol.disk_total_bytes

  function handleSave() {
    const body: Parameters<typeof updateVolume.mutate>[0]['body'] = {}
    if (editPath !== vol.path) body.path = editPath
    if (clearAlloc) body.clear_allocation = true
    else if (editAlloc !== '' && Number(editAlloc) !== vol.allocated_gb) body.allocated_gb = Number(editAlloc)
    updateVolume.mutate({ name: vol.name, body }, { onSuccess: () => setEditing(false) })
  }

  return (
    <div className={`border rounded-md ${vol.warning ? 'border-[#d4a72c]' : 'border-[#d0d7de]'} bg-white`}>
      <div className="px-4 py-3 flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span className="font-semibold text-sm text-[#1f2328]">{vol.name}</span>
            {vol.in_queue && (
              <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-[#dafbe1] text-[#1a7f37] border border-[#4ac26b55]">
                queue #{queueIndex + 1}
              </span>
            )}
            {!vol.available && (
              <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-[#eaeef2] text-[#656d76] border border-[#d0d7de]">
                unavailable
              </span>
            )}
            {vol.warning && (
              <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-[#fff8c5] text-[#9a6700] border border-[#d4a72c55]">
                ⚠ low space
              </span>
            )}
          </div>
          <p className="text-xs text-[#656d76] font-mono truncate">{vol.path}</p>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          {vol.in_queue && (
            <>
              <button
                onClick={onMoveUp}
                disabled={queueIndex === 0}
                className="text-xs px-1.5 py-1 rounded text-[#656d76] hover:text-[#1f2328] hover:bg-[#f6f8fa] disabled:opacity-30 disabled:cursor-not-allowed"
                title="Move up in queue"
              >▲</button>
              <button
                onClick={onMoveDown}
                disabled={queueIndex === queueLength - 1}
                className="text-xs px-1.5 py-1 rounded text-[#656d76] hover:text-[#1f2328] hover:bg-[#f6f8fa] disabled:opacity-30 disabled:cursor-not-allowed"
                title="Move down in queue"
              >▼</button>
              <button
                onClick={onRemoveFromQueue}
                className="text-xs px-1.5 py-1 rounded text-[#656d76] hover:text-[#d1242f] hover:bg-[#f6f8fa]"
                title="Remove from write queue"
              >✕ queue</button>
            </>
          )}
          {!vol.in_queue && (
            <button
              onClick={onAddToQueue}
              className="text-xs px-2 py-1 rounded border border-[#d0d7de] text-[#656d76] hover:bg-[#f6f8fa]"
              title="Add to write queue"
            >+ queue</button>
          )}
          <button
            onClick={() => { setEditing(e => !e); setConfirmRemove(false) }}
            className="text-xs px-1.5 py-1 rounded text-[#656d76] hover:text-[#0969da] hover:bg-[#f6f8fa]"
            title="Edit volume"
          >✎</button>
          {confirmRemove ? (
            <>
              <button
                onClick={() => {
                  setRemoveError(null)
                  removeVolume.mutate(vol.name, {
                    onError: (e) => setRemoveError(e instanceof Error ? e.message : String(e)),
                    onSuccess: () => setConfirmRemove(false),
                  })
                }}
                disabled={removeVolume.isPending}
                className="text-xs px-2 py-1 rounded bg-[#d1242f] text-white hover:bg-[#b91c1c] disabled:opacity-50"
              >Confirm</button>
              <button onClick={() => { setConfirmRemove(false); setRemoveError(null) }} className="text-xs px-1.5 py-1 text-[#656d76] hover:underline">Cancel</button>
            </>
          ) : (
            <button
              onClick={() => { setConfirmRemove(true); setEditing(false); setRemoveError(null) }}
              className="text-xs px-1.5 py-1 rounded text-[#656d76] hover:text-[#d1242f] hover:bg-[#f6f8fa]"
              title="Delete volume from config (does not delete files)"
            >✕</button>
          )}
        </div>
      </div>

      {removeError && (
        <div className="px-4 pb-3">
          <p className="text-xs text-[#d1242f] bg-[#ffebe9] border border-[#d1242f33] rounded px-3 py-2">{removeError}</p>
        </div>
      )}

      {/* Usage bars */}
      {vol.available && (
        <div className="px-4 pb-3 space-y-2">
          {allocBytes !== null && (
            <div>
              <div className="flex justify-between text-[10px] text-[#656d76] mb-0.5">
                <span>Civex usage</span>
                <span>{fmtBytes(vol.civex_used_bytes)} / {fmtBytes(allocBytes)}</span>
              </div>
              <UsageBar used={vol.civex_used_bytes} total={allocBytes} warn={vol.warning} />
            </div>
          )}
          {diskTotal !== null && (
            <div>
              <div className="flex justify-between text-[10px] text-[#656d76] mb-0.5">
                <span>Disk free</span>
                <span>{fmtBytes(vol.disk_free_bytes)} of {fmtBytes(diskTotal)}</span>
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
        <div className="border-t border-[#d0d7de] px-4 py-3 bg-[#f6f8fa] space-y-2 rounded-b-md">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-semibold text-[#656d76] uppercase tracking-wide">Path</label>
            <div className="flex gap-2">
              <input
                value={editPath}
                onChange={e => setEditPath(normalizePath(e.target.value))}
                onBlur={e => setEditPath(normalizePath(e.target.value))}
                className={inputCls}
              />
              {isDesktop && (
                <Button size="sm" onClick={async () => {
                  const p = await browseFolderDesktop()
                  if (p) setEditPath(p)
                }}>Browse…</Button>
              )}
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-semibold text-[#656d76] uppercase tracking-wide">Allocation (GB)</label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min="0.1"
                step="0.1"
                value={clearAlloc ? '' : editAlloc}
                onChange={e => { setEditAlloc(e.target.value); setClearAlloc(false) }}
                placeholder="unlimited"
                className={inputCls}
                disabled={clearAlloc}
              />
              <label className="flex items-center gap-1.5 text-xs text-[#656d76] whitespace-nowrap cursor-pointer select-none">
                <input type="checkbox" checked={clearAlloc} onChange={e => setClearAlloc(e.target.checked)} />
                Unlimited
              </label>
            </div>
          </div>
          {updateVolume.error && <p className="text-xs text-[#d1242f]">{String(updateVolume.error)}</p>}
          <div className="flex gap-2">
            <Button variant="primary" size="sm" onClick={handleSave} disabled={updateVolume.isPending}>
              {updateVolume.isPending ? 'Saving…' : 'Save'}
            </Button>
            <Button size="sm" onClick={() => setEditing(false)}>Cancel</Button>
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
      { name: name.trim(), path: path.trim(), allocated_gb: allocStr ? Number(allocStr) : null },
      { onSuccess: onDone },
    )
  }

  return (
    <div className="border border-dashed border-[#0969da55] rounded-md p-4 bg-[#f6f8fa] space-y-3">
      <p className="text-xs font-semibold text-[#0969da] uppercase tracking-wide">New volume</p>
      <div className="grid grid-cols-3 gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-[#656d76]">Name <span className="text-[#818b98]">(letters, digits, - _)</span></label>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="e.g. external"
            autoFocus
            className={inputCls}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-[#656d76]">Path</label>
          <div className="flex gap-2">
            <input
              value={path}
              onChange={e => setPath(normalizePath(e.target.value))}
              onBlur={e => setPath(normalizePath(e.target.value))}
              placeholder="/media/WD-8TB/civex-objects"
              className={inputCls}
            />
            {isDesktop && (
              <Button size="sm" onClick={async () => {
                const p = await browseFolderDesktop()
                if (p) setPath(p)
              }}>Browse…</Button>
            )}
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-[#656d76]">Allocation (GB, optional)</label>
          <input
            type="number"
            min="0.1"
            step="0.1"
            value={allocStr}
            onChange={e => setAllocStr(e.target.value)}
            placeholder="unlimited"
            className={inputCls}
          />
        </div>
      </div>
      {addVolume.error && <p className="text-xs text-[#d1242f]">{String(addVolume.error)}</p>}
      <div className="flex gap-2">
        <Button variant="primary" size="sm" onClick={handleAdd} disabled={addVolume.isPending || !name.trim() || !path.trim()}>
          {addVolume.isPending ? 'Adding…' : 'Add volume'}
        </Button>
        <Button size="sm" onClick={onDone}>Cancel</Button>
      </div>
    </div>
  )
}

export default function StorePage() {
  const { data: volumes, isLoading, error } = useVolumes()
  const setQueue = useSetQueue()
  const [addingVolume, setAddingVolume] = useState(false)

  if (isLoading) return <LoadingState />
  if (error || !volumes) return <ErrorState message={error ? String(error) : 'Failed to load volumes'} />

  const queue = volumes.filter(v => v.in_queue).sort((a, b) => {
    const qi = volumes.filter(v => v.in_queue).map(v => v.name)
    return qi.indexOf(a.name) - qi.indexOf(b.name)
  })
  const queueNames = queue.map(v => v.name)

  function moveInQueue(name: string, dir: -1 | 1) {
    const idx = queueNames.indexOf(name)
    const next = [...queueNames]
    const swap = idx + dir
    ;[next[idx], next[swap]] = [next[swap], next[idx]]
    setQueue.mutate(next)
  }

  function removeFromQueue(name: string) {
    setQueue.mutate(queueNames.filter(n => n !== name))
  }

  function addToQueue(name: string) {
    setQueue.mutate([...queueNames, name])
  }

  const hasWarning = volumes.some(v => v.warning)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-[#1f2328]">Storage</h1>
          <p className="text-sm text-[#656d76] mt-0.5">
            Configure where civex stores files. New uploads go to the first available volume in the write queue.
          </p>
        </div>
        {!addingVolume && (
          <Button size="sm" onClick={() => setAddingVolume(true)}>+ Add volume</Button>
        )}
      </div>

      {hasWarning && (
        <div className="border border-[#d4a72c] rounded-md px-4 py-3 bg-[#fff8c5] text-sm text-[#9a6700]">
          ⚠ One or more volumes are running low on space. Consider adding a new volume or freeing disk space.
        </div>
      )}

      {addingVolume && (
        <AddVolumeForm onDone={() => setAddingVolume(false)} />
      )}

      <div className="space-y-3">
        {volumes.length === 0 && (
          <p className="text-sm text-[#656d76] italic">No volumes configured.</p>
        )}
        {volumes.map(vol => {
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

      <div className="border border-[#d0d7de] rounded-md px-4 py-3 bg-[#f6f8fa] text-xs text-[#656d76] space-y-1">
        <p><span className="font-semibold text-[#1f2328]">Write queue:</span> {queueNames.length ? queueNames.join(' → ') : 'empty'}</p>
        <p>Civex tries each volume in order. A volume is skipped if its allocation is full or disk space is below the headroom threshold.</p>
      </div>
    </div>
  )
}
