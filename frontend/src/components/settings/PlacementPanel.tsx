import { Link } from 'react-router'
import { Button } from '../ui'
import { useClearPlacement, usePlacements } from '../../hooks/useStore'
import { errorMessage } from '../../lib/errors'

/** Which collections have a home volume. Read-only apart from clearing: a
 * home is chosen on the collection's own page. */
export function PlacementPanel() {
  const { data: placements = [] } = usePlacements()
  const clear = useClearPlacement()

  if (placements.length === 0) return null

  return (
    <div className="border border-border rounded-md bg-canvas">
      <div className="px-4 py-3 border-b border-border">
        <h3 className="text-sm font-semibold text-fg">Collection homes</h3>
        <p className="text-xs text-fg-muted mt-0.5">
          These collections write new files to their own volume first. Existing
          files are reused wherever they are stored. Change a home on the
          collection&apos;s page.
        </p>
      </div>
      <ul className="divide-y divide-border">
        {placements.map((p) => (
          <li
            key={p.collection_id}
            className="px-4 py-2 flex items-center justify-between gap-3 text-sm"
          >
            <span className="min-w-0 truncate">
              {p.collection_name ? (
                <Link
                  to={`/collections/${p.collection_id}`}
                  className="text-accent hover:underline"
                >
                  {p.collection_name}
                </Link>
              ) : (
                <span className="text-fg-muted italic">
                  (deleted collection)
                </span>
              )}
              <span className="text-fg-muted">
                {' '}
                → {p.volume}
                {p.on_unavailable === 'fail' ? ' · refuses if unavailable' : ''}
              </span>
            </span>
            <Button
              size="sm"
              disabled={clear.isPending}
              onClick={() => clear.mutate(p.collection_id)}
            >
              Clear
            </Button>
          </li>
        ))}
      </ul>
      {clear.isError && (
        <p role="alert" className="px-4 pb-3 text-xs text-danger">
          {errorMessage(clear.error)}
        </p>
      )}
    </div>
  )
}
