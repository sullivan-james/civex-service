import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useCollections } from '../../../hooks/useCollections'
import {
  useAllCollectionStorage,
  usePlacements,
  useVolumes,
} from '../../../hooks/useStore'
import { useTransfers } from '../../../hooks/useTransfers'
import { errorMessage } from '../../../lib/errors'
import { formatSize } from '../../../utils/storage'
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  ErrorState,
  InfoTip,
  Page,
  Skeleton,
  TabNav,
  TabPanel,
  useTabParam,
} from '../../ui'
import { Network } from '../../ui/icons'
import { NewTransferModal, type TransferPreset } from './NewTransferModal'
import { StatusDot } from './StatusDot'
import { TransferCard } from './TransferCard'
import { useVolumeActions } from './useVolumeActions'
import { NEEDS_ATTENTION, STATE_LABEL } from './volumeState'
import { VolumeSpace } from './VolumeSpace'

const STORAGE = '/settings/storage'
const VOLUME_TABS = [{ id: 'contents' }, { id: 'moves' }] as const

interface ContentRow {
  key: string
  name: string
  files: number
  bytes: number
  muted?: boolean
  collectionId?: string
  home?: boolean
  shared?: number
  note?: string
  kind: 'collection' | 'history' | 'unused'
}

/** One volume: its state and space in the header, then tabs for what is on it
 * and the moves that involve it. */
export default function VolumePage() {
  const { name = '' } = useParams()
  const navigate = useNavigate()
  const { data: volumes, isLoading, error } = useVolumes()
  const { data: placements = [] } = usePlacements()
  const { data: spreads = [] } = useAllCollectionStorage()
  const { data: collections = [] } = useCollections()
  const { data: transfers = [] } = useTransfers()
  const actions = useVolumeActions(() => navigate(STORAGE))
  const [moving, setMoving] = useState<TransferPreset | null>(null)
  const [tab, setTab] = useTabParam(VOLUME_TABS, 'contents')

  const vol = volumes?.find((v) => v.name === name)

  // Collections on this volume: those with files here, and those whose home it
  // is (which may have none yet).
  const rows = useMemo(() => {
    const names = new Map(collections.map((c) => [c.id, c.name]))
    const byId = new Map<
      string,
      {
        id: string
        files: number
        bytes: number
        shared: number
        home: boolean
      }
    >()
    for (const r of spreads) {
      const share = r.volumes.find((v) => v.volume === name)
      if (share)
        byId.set(r.collection_id, {
          id: r.collection_id,
          files: share.files,
          bytes: share.bytes,
          shared: share.shared_files,
          home: false,
        })
    }
    for (const p of placements.filter((p) => p.volume === name)) {
      const row = byId.get(p.collection_id)
      if (row) row.home = true
      else
        byId.set(p.collection_id, {
          id: p.collection_id,
          files: 0,
          bytes: 0,
          shared: 0,
          home: true,
        })
    }
    return [...byId.values()]
      .map((r) => ({ ...r, name: names.get(r.id) ?? 'A deleted collection' }))
      .sort((a, b) => b.bytes - a.bytes || a.name.localeCompare(b.name))
  }, [collections, spreads, placements, name])

  if (isLoading)
    return (
      <div className="space-y-3" aria-hidden="true">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  if (error) return <ErrorState message={errorMessage(error)} />
  if (!vol)
    return (
      <Page breadcrumbs={crumbs(name)}>
        <EmptyState
          title={`No volume called “${name}”`}
          message="It may have been removed."
        />
      </Page>
    )

  const attention = NEEDS_ATTENTION.includes(vol.state)
  const total = vol.civex_used_bytes ?? rows.reduce((n, r) => n + r.bytes, 0)
  const queueIndex = actions.queueNames.indexOf(vol.name)
  const mine = transfers.filter(
    (t) =>
      t.spec.sources.includes(vol.name) || t.spec.targets.includes(vol.name),
  )
  const homed = placements.filter((p) => p.volume === vol.name).length

  const contents: ContentRow[] = [
    ...rows.map((r): ContentRow => ({
      key: r.id,
      name: r.name,
      files: r.files,
      bytes: r.bytes,
      collectionId: r.id,
      home: r.home,
      shared: r.shared,
      kind: 'collection',
    })),
    ...(vol.history_files > 0
      ? [
          {
            key: '__history',
            name: 'Workflow run history',
            files: vol.history_files,
            bytes: vol.history_bytes,
            muted: true,
            note: 'Kept because a workflow run took these files as input. No collection uses them now.',
            kind: 'history' as const,
          },
        ]
      : []),
    ...(vol.unused_files > 0
      ? [
          {
            key: '__unused',
            name: 'Unused',
            files: vol.unused_files,
            bytes: vol.unused_bytes,
            muted: true,
            note: 'Nothing uses these files. Cleaning up reclaims the space.',
            kind: 'unused' as const,
          },
        ]
      : []),
  ]

  const tabs = [
    { id: 'contents' as const, label: 'Contents' },
    ...(mine.length > 0
      ? [{ id: 'moves' as const, label: `Moves (${mine.length})` }]
      : []),
  ]
  const shownTab = tab === 'moves' && mine.length === 0 ? 'contents' : tab

  return (
    <Page
      breadcrumbs={crumbs(vol.name)}
      title={
        <span className="flex flex-wrap items-center gap-3">
          {vol.name}
          <span className="inline-flex items-center gap-2 text-sm font-normal">
            <StatusDot state={vol.state} />
            {STATE_LABEL[vol.state]}
          </span>
          {vol.network && (
            <Badge variant="accent">
              <Network size={12} className="mr-1" aria-hidden="true" />
              Network
            </Badge>
          )}
        </span>
      }
      action={
        attention && vol.state === 'wrong_drive' ? (
          <Button variant="primary" onClick={() => actions.adopt(vol)}>
            This is the right drive…
          </Button>
        ) : undefined
      }
      secondaryActions={[
        { label: 'Edit…', onClick: () => actions.edit(vol) },
        {
          label:
            queueIndex >= 0 ? 'Remove from write order' : 'Add to write order',
          onClick: () => actions.toggleQueue(vol.name),
        },
        ...(attention
          ? []
          : [
              {
                label: 'Move everything off…',
                onClick: () => setMoving({ source: vol.name }),
              },
            ]),
        {
          label: 'Remove…',
          variant: 'danger' as const,
          onClick: () => actions.remove(vol),
        },
      ]}
      tabs={
        tabs.length > 1 ? (
          <TabNav
            label="Volume"
            tabs={tabs}
            value={shownTab}
            onChange={setTab}
          />
        ) : undefined
      }
    >
      <div className="space-y-3">
        <p className="break-all font-mono text-xs text-fg-muted">{vol.path}</p>
        {attention && (
          <div
            role="alert"
            className="flex items-center gap-2 rounded-md border border-attention-muted bg-attention-subtle px-4 py-3 text-sm"
          >
            <span
              className={
                vol.state === 'wrong_drive' ? 'text-danger' : 'text-attention'
              }
            >
              {vol.reason}
            </span>
            <InfoTip>
              {vol.fix} The list below comes from Civex&apos;s records, so it is
              complete even while the drive is away; its files can&apos;t be
              opened until it is back.
            </InfoTip>
          </div>
        )}
        <div className="grid items-center gap-x-8 gap-y-2 md:grid-cols-[minmax(0,24rem)_1fr]">
          <VolumeSpace vol={vol} />
          <p className="flex flex-wrap gap-2 text-sm">
            <Badge variant={queueIndex >= 0 ? 'accent' : 'default'}>
              {queueIndex >= 0
                ? `Write order #${queueIndex + 1}`
                : 'Not in write order'}
            </Badge>
            {homed > 0 && (
              <Badge>
                Home of {homed} {homed === 1 ? 'collection' : 'collections'}
              </Badge>
            )}
          </p>
        </div>
      </div>

      <TabPanel id="contents" value={shownTab}>
        <DataTable
          layout="auto"
          columns={[
            {
              key: 'name',
              header: 'Collection',
              render: (r: ContentRow) => (
                <>
                  <span className="font-medium">{r.name}</span>
                  {r.home && (
                    <span className="ml-2 text-xs text-fg-muted">home</span>
                  )}
                  {r.note && <InfoTip>{r.note}</InfoTip>}
                  {!!r.shared && (
                    <InfoTip>
                      {r.shared} {r.shared === 1 ? 'file is' : 'files are'} also
                      used by other collections, so rows can add up to more than
                      the volume holds.
                    </InfoTip>
                  )}
                </>
              ),
            },
            {
              key: 'files',
              header: 'Files',
              render: (r) => r.files.toLocaleString(),
            },
            { key: 'size', header: 'Size', render: (r) => formatSize(r.bytes) },
            {
              key: 'share',
              header: 'Share',
              width: '12rem',
              render: (r) => (
                <ShareBar bytes={r.bytes} total={total} muted={r.muted} />
              ),
            },
          ]}
          rows={contents}
          getRowId={(r) => r.key}
          rowHref={(r) =>
            r.collectionId ? `/collections/${r.collectionId}` : undefined
          }
          onRowClick={(r) => {
            if (r.kind === 'unused') navigate(`${STORAGE}?tab=tasks`)
          }}
          emptyTitle="Nothing is stored here yet"
          actionsWidth="8rem"
          actions={(r) =>
            r.kind === 'collection' && r.files > 0 ? (
              <Button
                size="sm"
                variant="link"
                onClick={() => setMoving({ collectionId: r.collectionId })}
              >
                Move…
              </Button>
            ) : r.kind === 'unused' ? (
              <Button size="sm" variant="link" to={`${STORAGE}?tab=tasks`}>
                Clean up
              </Button>
            ) : null
          }
        />
      </TabPanel>

      <TabPanel id="moves" value={shownTab}>
        <ul className="space-y-3">
          {mine.map((t) => (
            <TransferCard key={t.id} t={t} />
          ))}
        </ul>
      </TabPanel>

      {actions.dialogs}
      {moving && (
        <NewTransferModal preset={moving} onClose={() => setMoving(null)} />
      )}
    </Page>
  )
}

function crumbs(name: string) {
  return [
    { label: 'Settings', to: '/settings' },
    { label: 'Storage', to: STORAGE },
    { label: name },
  ]
}

function ShareBar({
  bytes,
  total,
  muted = false,
}: {
  bytes: number
  total: number
  muted?: boolean
}) {
  const pct = total > 0 ? Math.min(100, Math.round((bytes / total) * 100)) : 0
  return (
    <div
      role="img"
      aria-label={`${pct}% of this volume`}
      className="h-1.5 overflow-hidden rounded-full bg-canvas-inset"
    >
      <div
        className={muted ? 'h-full bg-fg-subtle' : 'h-full bg-accent'}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}
