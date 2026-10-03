import { Link, useNavigate } from 'react-router'
import type { VolumeStats } from '../../../api/store'
import { Badge, IconButton, Menu, Td, Tr, type MenuItem } from '../../ui'
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  MoreVertical,
  Network,
  Pencil,
  Trash2,
} from '../../ui/icons'
import { StatusDot } from './StatusDot'
import { VolumeSpace } from './VolumeSpace'
import { NEEDS_ATTENTION, STATE_LABEL } from './volumeState'

/** One volume: what it is and whether it can be used on one line, with what
 * to do about a problem right under its name. */
export function VolumeRow({
  vol,
  queueIndex,
  queueLength,
  collections,
  onEdit,
  onRemove,
  onAdopt,
  onMove,
  onToggleQueue,
}: {
  vol: VolumeStats
  /** Position in the write queue, or -1 when it isn't in it. */
  queueIndex: number
  queueLength: number
  /** How many collections have files on this volume or use it as their home. */
  collections: number
  onEdit: () => void
  onRemove: () => void
  onAdopt: () => void
  onMove: (delta: -1 | 1) => void
  onToggleQueue: () => void
}) {
  const navigate = useNavigate()
  const queued = queueIndex >= 0
  const attention = NEEDS_ATTENTION.includes(vol.state)
  const items: MenuItem[] = [
    { label: 'Edit…', icon: Pencil, onClick: onEdit },
    {
      label: queued ? 'Remove from write queue' : 'Add to write queue',
      onClick: onToggleQueue,
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
      ? [{ label: 'This is the right drive…', onClick: onAdopt }]
      : []),
    {
      label: 'Remove…',
      icon: Trash2,
      variant: 'danger' as const,
      onClick: onRemove,
    },
  ]

  return (
    <Tr>
      <Td className="align-top">
        <div className="flex items-center gap-2">
          <Link
            to={`/settings/storage/volumes/${encodeURIComponent(vol.name)}`}
            className="font-medium text-accent hover:underline"
          >
            {vol.name}
          </Link>
          {vol.network && (
            <Badge variant="accent">
              <Network size={11} className="mr-1" aria-hidden="true" />
              Network
            </Badge>
          )}
        </div>
        <p
          className="mt-0.5 max-w-[24rem] truncate font-mono text-xs text-fg-muted"
          title={vol.path}
        >
          {vol.path}
        </p>
        {attention && (
          <div className="mt-2 max-w-[24rem] space-y-1 text-xs">
            <p
              className={
                vol.state === 'wrong_drive' ? 'text-danger' : 'text-attention'
              }
            >
              {vol.reason}
            </p>
            {vol.fix && <p className="text-fg-muted">{vol.fix}</p>}
            {vol.state === 'wrong_drive' && (
              <button
                type="button"
                onClick={onAdopt}
                className="text-accent hover:underline cursor-pointer"
              >
                This is the right drive
              </button>
            )}
          </div>
        )}
      </Td>
      <Td className="align-top whitespace-nowrap">
        <span className="inline-flex items-center gap-2">
          <StatusDot state={vol.state} />
          {STATE_LABEL[vol.state]}
        </span>
        {vol.warning && vol.state === 'online' && (
          <p className="mt-1 flex items-center gap-1 text-xs text-attention">
            <AlertTriangle size={12} aria-hidden="true" /> Low space
          </p>
        )}
      </Td>
      <Td className="align-top">
        <VolumeSpace vol={vol} />
      </Td>
      <Td className="align-top whitespace-nowrap">
        {queued ? (
          <span className="inline-flex items-center gap-1">
            <span className="w-5 text-fg-muted">#{queueIndex + 1}</span>
            <IconButton
              icon={ArrowUp}
              size="sm"
              aria-label={`Move ${vol.name} earlier in the write queue`}
              disabled={queueIndex === 0}
              onClick={() => onMove(-1)}
            />
            <IconButton
              icon={ArrowDown}
              size="sm"
              aria-label={`Move ${vol.name} later in the write queue`}
              disabled={queueIndex === queueLength - 1}
              onClick={() => onMove(1)}
            />
          </span>
        ) : (
          <span className="text-fg-subtle">Not in queue</span>
        )}
      </Td>
      <Td className="align-top whitespace-nowrap">
        {collections > 0 ? (
          <Link
            to={`/settings/storage/volumes/${encodeURIComponent(vol.name)}`}
            className="text-accent hover:underline"
          >
            {collections} {collections === 1 ? 'collection' : 'collections'}
          </Link>
        ) : (
          <span className="text-fg-subtle">—</span>
        )}
      </Td>
      <Td className="align-top text-right">
        <Menu
          items={items}
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
      </Td>
    </Tr>
  )
}
