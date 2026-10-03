import { useEffect, useRef, useState } from 'react'
import { useBrowse, useCreateFolder } from '../../hooks/useStore'
import type { StorageLocation } from '../../api/store'
import {
  Button,
  Checkbox,
  IconButton,
  Input,
  ListButton,
  Skeleton,
} from '../ui'
import {
  ArrowUp,
  ChevronRight,
  Folder,
  FolderOpen,
  FolderPlus,
  HardDrive,
  House,
  Network,
  RefreshCw,
} from '../ui/icons'
import { errorMessage } from '../../lib/errors'
import { breadcrumbs, formatSize } from '../../utils/storage'

/** The place the current folder is inside of: the most specific match. */
function activePlace(
  places: StorageLocation[],
  path: string | undefined,
): string | null {
  if (!path) return null
  let best: StorageLocation | null = null
  for (const place of places) {
    const base = place.path.replace(/\/$/, '')
    if (path === place.path || path === base || path.startsWith(`${base}/`)) {
      if (!best || place.path.length > best.path.length) best = place
    }
  }
  return best?.path ?? null
}

function PlaceIcon({ place }: { place: StorageLocation }) {
  const cls = 'shrink-0 text-fg-muted'
  if (place.kind === 'home') return <House size={16} className={cls} />
  if (place.kind === 'project') return <FolderOpen size={16} className={cls} />
  return place.network ? (
    <Network size={16} className="shrink-0 text-accent" />
  ) : (
    <HardDrive size={16} className={cls} />
  )
}

function PlaceButton({
  place,
  active,
  onOpen,
}: {
  place: StorageLocation
  active: boolean
  onOpen: () => void
}) {
  const detail = place.network
    ? (place.source ?? 'Network drive')
    : place.free_bytes != null && place.total_bytes != null
      ? `${formatSize(place.free_bytes)} free of ${formatSize(place.total_bytes)}`
      : null
  return (
    <li>
      <ListButton
        onClick={onOpen}
        active={active}
        aria-current={active ? 'true' : undefined}
        className="flex items-start gap-2 rounded-md"
      >
        <span className="mt-0.5">
          <PlaceIcon place={place} />
        </span>
        <span className="min-w-0">
          <span className="block text-sm text-fg truncate">{place.label}</span>
          {detail && (
            <span className="block text-xs text-fg-muted truncate">
              {detail}
            </span>
          )}
        </span>
      </ListButton>
    </li>
  )
}

/** Browse the folders on the machine running Civex and pick one. A browser's
 * own folder dialog can't give a server-side path, so this lists the
 * server's folders itself: with the project, home and mounted drives
 * (network drives marked) to start from. */
export function FolderBrowser({
  initialPath,
  onSelect,
  onCancel,
  selectLabel = 'Choose this folder',
}: {
  initialPath?: string
  onSelect: (path: string) => void
  onCancel: () => void
  selectLabel?: string
}) {
  const [path, setPath] = useState<string | undefined>(initialPath || undefined)
  const [showHidden, setShowHidden] = useState(false)
  const [naming, setNaming] = useState<string | null>(null)
  const {
    data: listing,
    error,
    isLoading,
    isFetching,
    refetch,
  } = useBrowse(path, showHidden)
  const createFolder = useCreateFolder()

  // A starting folder that can't be opened (typed with a typo, drive gone)
  // falls back to the home folder instead of leaving an empty browser.
  const triedInitial = useRef(false)
  useEffect(() => {
    if (error && path && path === initialPath && !triedInitial.current) {
      triedInitial.current = true
      setPath(undefined)
    }
  }, [error, path, initialPath])

  const places = listing?.locations ?? []
  const here = listing?.path
  const current = activePlace(places, here)
  const starts = places.filter((p) => p.kind !== 'drive')
  const drives = places.filter((p) => p.kind === 'drive')

  function create() {
    if (!here || !naming?.trim()) return
    createFolder.mutate(
      { parent: here, name: naming.trim() },
      {
        onSuccess: (made) => {
          setNaming(null)
          setPath(made.path)
        },
      },
    )
  }

  return (
    <div className="flex flex-col h-[30rem] max-h-[70vh]">
      <div className="flex flex-1 min-h-0">
        <nav
          aria-label="Places"
          className="w-52 shrink-0 border-r border-border overflow-y-auto p-2 space-y-3 bg-canvas-subtle"
        >
          <div>
            <p className="px-2 pb-1 text-xs font-semibold uppercase tracking-wide text-fg-muted">
              Places
            </p>
            <ul className="space-y-0.5">
              {starts.map((p) => (
                <PlaceButton
                  key={p.path + p.kind}
                  place={p}
                  active={
                    current === p.path && !drives.some((d) => d.path === p.path)
                  }
                  onOpen={() => setPath(p.path)}
                />
              ))}
            </ul>
          </div>
          <div>
            <div className="flex items-center justify-between px-2 pb-1">
              <p className="text-xs font-semibold uppercase tracking-wide text-fg-muted">
                Drives
              </p>
              <IconButton
                icon={RefreshCw}
                aria-label="Rescan drives"
                disabled={isFetching}
                onClick={() => refetch()}
                iconProps={{
                  className: isFetching ? 'animate-spin' : undefined,
                }}
              />
            </div>
            {drives.length === 0 ? (
              <p className="px-2 text-xs text-fg-muted">
                {isLoading ? 'Looking…' : 'No other drives found.'}
              </p>
            ) : (
              <ul className="space-y-0.5">
                {drives.map((d) => (
                  <PlaceButton
                    key={d.path}
                    place={d}
                    active={current === d.path}
                    onOpen={() => setPath(d.path)}
                  />
                ))}
              </ul>
            )}
            <p className="mt-2 px-2 text-xs text-fg-muted">
              {listing?.hint ??
                'A drive is listed once your computer has mounted it. Plugged one in just now? Rescan.'}
            </p>
          </div>
        </nav>

        <section className="flex-1 min-w-0 flex flex-col">
          <div className="flex items-center gap-2 border-b border-border px-3 py-2">
            <Button
              size="sm"
              aria-label="Up one folder"
              disabled={!listing?.parent}
              onClick={() => listing?.parent && setPath(listing.parent)}
            >
              <ArrowUp size={14} />
            </Button>
            <ol
              aria-label="Current folder"
              className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto text-sm whitespace-nowrap"
            >
              {here &&
                breadcrumbs(here).map((c, i, all) => (
                  <li key={c.path} className="flex items-center gap-0.5">
                    {i > 0 && (
                      <ChevronRight size={12} className="text-fg-muted" />
                    )}
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setPath(c.path)}
                      aria-current={
                        i === all.length - 1 ? 'location' : undefined
                      }
                      className={i === all.length - 1 ? 'font-semibold' : ''}
                    >
                      {c.label}
                    </Button>
                  </li>
                ))}
            </ol>
            <label className="flex items-center gap-1.5 text-xs text-fg-muted shrink-0 cursor-pointer">
              <Checkbox
                checked={showHidden}
                onChange={(e) => setShowHidden(e.target.checked)}
              />
              Hidden
            </label>
            <Button
              size="sm"
              disabled={!here}
              onClick={() => setNaming(naming === null ? '' : null)}
            >
              <FolderPlus size={14} /> New folder
            </Button>
          </div>

          {naming !== null && (
            <form
              className="flex items-center gap-2 border-b border-border bg-canvas-subtle px-3 py-2"
              onSubmit={(e) => {
                e.preventDefault()
                create()
              }}
            >
              <Input
                autoFocus
                aria-label="New folder name"
                value={naming}
                onChange={(e) => setNaming(e.target.value)}
                placeholder="New folder name"
                className="flex-1"
              />
              <Button
                type="submit"
                size="sm"
                variant="primary"
                disabled={!naming.trim() || createFolder.isPending}
              >
                Create
              </Button>
              <Button size="sm" onClick={() => setNaming(null)}>
                Cancel
              </Button>
            </form>
          )}
          {createFolder.isError && (
            <p role="alert" className="px-3 pt-2 text-xs text-danger">
              {errorMessage(createFolder.error)}
            </p>
          )}

          <div
            className={`flex-1 min-h-0 overflow-y-auto ${isFetching && listing ? 'opacity-60' : ''}`}
          >
            {isLoading ? (
              <div className="space-y-2 p-3" aria-hidden="true">
                <Skeleton className="h-6 w-full" />
                <Skeleton className="h-6 w-3/4" />
                <Skeleton className="h-6 w-2/3" />
              </div>
            ) : error && !listing ? (
              <div role="alert" className="p-4 space-y-3">
                <p className="text-sm text-danger">{errorMessage(error)}</p>
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => refetch()}>
                    Try again
                  </Button>
                  <Button size="sm" onClick={() => setPath(undefined)}>
                    Go to home
                  </Button>
                </div>
              </div>
            ) : listing ? (
              <>
                {error && (
                  <p role="alert" className="px-3 pt-2 text-xs text-danger">
                    {errorMessage(error)}
                  </p>
                )}
                {listing.entries.length === 0 ? (
                  <p className="p-4 text-sm text-fg-muted">
                    No folders here. You can still choose this folder, or make a
                    new one.
                  </p>
                ) : (
                  <ul className="divide-y divide-border">
                    {listing.entries.map((entry) => (
                      <li key={entry.path}>
                        <ListButton
                          onClick={() => setPath(entry.path)}
                          className="flex items-center gap-2"
                        >
                          <Folder
                            size={16}
                            className="shrink-0 text-fg-muted"
                          />
                          <span className="truncate text-fg">{entry.name}</span>
                          <ChevronRight
                            size={14}
                            className="ml-auto shrink-0 text-fg-muted"
                          />
                        </ListButton>
                      </li>
                    ))}
                  </ul>
                )}
                {listing.truncated && (
                  <p className="px-3 py-2 text-xs text-fg-muted">
                    Only the first folders are shown. Type a more specific path
                    to reach the rest.
                  </p>
                )}
              </>
            ) : null}
          </div>
        </section>
      </div>

      <div className="flex items-center gap-3 border-t border-border px-5 py-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs text-fg-muted">Selected folder</p>
          <p className="font-mono text-sm text-fg truncate" title={here}>
            {here ?? '—'}
          </p>
        </div>
        <Button onClick={onCancel}>Cancel</Button>
        <Button
          variant="primary"
          disabled={!here || (!!error && !listing)}
          onClick={() => here && onSelect(here)}
        >
          {selectLabel}
        </Button>
      </div>
    </div>
  )
}
