import { useState } from 'react'
import { useNavigate } from 'react-router'
import type { VolumeStats } from '../../../api/store'
import {
  useAllCollectionStorage,
  usePlacements,
  useVolumes,
} from '../../../hooks/useStore'
import {
  Badge,
  Button,
  Card,
  DataTable,
  ErrorState,
  IconButton,
  InfoTip,
  Menu,
  Skeleton,
  SortableList,
  type MenuItem,
} from '../../ui'
import {
  AlertTriangle,
  MoreVertical,
  Network,
  Pencil,
  Plus,
  Trash2,
} from '../../ui/icons'
import { errorMessage } from '../../../lib/errors'
import { formatSize } from '../../../utils/storage'
import { AddVolumeModal } from '../AddVolumeModal'
import { StatusDot } from './StatusDot'
import { useVolumeActions } from './useVolumeActions'
import { VolumeSpace } from './VolumeSpace'
import { NEEDS_ATTENTION, STATE_LABEL } from './volumeState'

/** The volumes Civex keeps files on, one row each, and the order new files
 * are written in. */
export function VolumesTab() {
  const { data: volumes, isLoading, error } = useVolumes()
  const { data: placements = [] } = usePlacements()
  const { data: spreads = [] } = useAllCollectionStorage()
  const actions = useVolumeActions()
  const navigate = useNavigate()
  const [adding, setAdding] = useState(false)

  if (isLoading)
    return (
      <div className="space-y-3" aria-hidden="true">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  if (error || !volumes)
    return (
      <ErrorState
        message={error ? errorMessage(error) : 'Failed to load volumes'}
      />
    )

  // Collections with files on a volume, or that use it as their home.
  const collectionsOn = (name: string) =>
    new Set([
      ...placements
        .filter((p) => p.volume === name)
        .map((p) => p.collection_id),
      ...spreads
        .filter((r) => r.volumes.some((v) => v.volume === name))
        .map((r) => r.collection_id),
    ]).size
  const attention = volumes.filter((v) => NEEDS_ATTENTION.includes(v.state))
  const used = volumes
    .filter((v) => v.available)
    .reduce((sum, v) => sum + (v.civex_used_bytes ?? 0), 0)
  const queued = volumes.filter((v) => v.in_queue)
  const byName = new Map(volumes.map((v) => [v.name, v]))
  const ordered = actions.queueNames
    .map((n) => byName.get(n))
    .filter((v): v is VolumeStats => !!v)

  function menuItems(vol: VolumeStats): MenuItem[] {
    const inQueue = actions.queueNames.includes(vol.name)
    return [
      { label: 'Edit…', icon: Pencil, onClick: () => actions.edit(vol) },
      {
        label: inQueue ? 'Remove from write order' : 'Add to write order',
        onClick: () => actions.toggleQueue(vol.name),
      },
      ...(vol.state === 'online' || vol.state === 'readonly'
        ? [
            {
              label: 'Move files off this volume…',
              onClick: () =>
                navigate(
                  `/settings/storage?tab=tasks&from=${encodeURIComponent(vol.name)}`,
                ),
            },
          ]
        : []),
      ...(vol.state === 'wrong_drive'
        ? [
            {
              label: 'This is the right drive…',
              onClick: () => actions.adopt(vol),
            },
          ]
        : []),
      {
        label: 'Remove…',
        icon: Trash2,
        variant: 'danger' as const,
        onClick: () => actions.remove(vol),
      },
    ]
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-fg-muted">
          {volumes.length} {volumes.length === 1 ? 'volume' : 'volumes'} ·{' '}
          {formatSize(used)} used
        </p>
        <Button variant="primary" size="sm" onClick={() => setAdding(true)}>
          <Plus size={14} /> Add volume
        </Button>
      </div>

      {attention.length > 0 && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-md border border-attention-muted bg-attention-subtle px-4 py-3 text-sm text-attention"
        >
          <AlertTriangle size={16} className="shrink-0" aria-hidden="true" />
          {attention.length === 1
            ? `${attention[0].name} needs attention`
            : `${attention.length} volumes need attention: ${attention.map((v) => v.name).join(', ')}`}
        </div>
      )}

      <DataTable
        layout="auto"
        columns={[
          {
            key: 'volume',
            header: 'Volume',
            render: (vol) => (
              <>
                <span className="flex items-center gap-2 font-medium">
                  {vol.name}
                  {vol.network && (
                    <Badge variant="accent">
                      <Network size={12} className="mr-1" aria-hidden="true" />
                      Network
                    </Badge>
                  )}
                </span>
                <span
                  className="block max-w-96 truncate font-mono text-xs text-fg-muted"
                  title={vol.path}
                >
                  {vol.path}
                </span>
              </>
            ),
          },
          {
            key: 'status',
            header: 'Status',
            className: 'whitespace-nowrap',
            render: (vol) => (
              <>
                <span className="inline-flex items-center gap-2">
                  <StatusDot state={vol.state} />
                  {STATE_LABEL[vol.state]}
                  {NEEDS_ATTENTION.includes(vol.state) && (
                    <InfoTip>
                      {vol.reason}
                      {vol.fix ? ` ${vol.fix}` : ''}
                    </InfoTip>
                  )}
                </span>
                {vol.warning && vol.state === 'online' && (
                  <span className="mt-1 flex items-center gap-1 text-xs text-attention">
                    <AlertTriangle size={12} aria-hidden="true" /> Low space
                  </span>
                )}
              </>
            ),
          },
          {
            key: 'space',
            header: 'Space',
            render: (vol) => <VolumeSpace vol={vol} />,
          },
          {
            key: 'collections',
            header: 'Collections',
            render: (vol) => {
              const n = collectionsOn(vol.name)
              return n > 0 ? n : <span className="text-fg-subtle">—</span>
            },
          },
        ]}
        rows={volumes}
        getRowId={(vol) => vol.name}
        rowHref={(vol) =>
          `/settings/storage/volumes/${encodeURIComponent(vol.name)}`
        }
        emptyTitle="No volumes yet"
        emptyAction={
          <Button variant="primary" size="sm" onClick={() => setAdding(true)}>
            <Plus size={14} /> Add volume
          </Button>
        }
        actionsWidth="4rem"
        actions={(vol) => (
          <Menu
            items={menuItems(vol)}
            trigger={({ open, toggle }) => (
              <IconButton
                icon={MoreVertical}
                aria-label={`Actions for ${vol.name}`}
                aria-haspopup="menu"
                aria-expanded={open}
                onClick={toggle}
              />
            )}
          />
        )}
      />

      {volumes.length > 0 && (
        <Card
          title={
            <>
              Write order
              <InfoTip>
                New files go to the first volume here that is online and has
                room. A volume outside this list is only used by collections
                that have it as their home.
              </InfoTip>
            </>
          }
          flush
        >
          {queued.length === 0 ? (
            <p className="px-4 py-3 text-sm text-fg-muted">None</p>
          ) : (
            <SortableList
              label="Write order"
              items={ordered}
              getKey={(v) => v.name}
              getLabel={(v) => v.name}
              moveButtons="always"
              onReorder={(next) =>
                actions.setQueueOrder(next.map((v) => v.name))
              }
              renderItem={(vol, i) => (
                <span className="flex min-h-12 items-center gap-3 px-2 text-sm">
                  <span className="w-5 text-fg-muted">{i + 1}</span>
                  <span className="font-medium">{vol.name}</span>
                  <StatusDot state={vol.state} />
                </span>
              )}
            />
          )}
        </Card>
      )}

      {adding && (
        <AddVolumeModal
          existingNames={volumes.map((v) => v.name)}
          onClose={() => setAdding(false)}
        />
      )}
      {actions.dialogs}
    </div>
  )
}
