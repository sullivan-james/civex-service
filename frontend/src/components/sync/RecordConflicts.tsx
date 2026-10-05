import { Link } from 'react-router'
import { useConflictsAbout } from '../../hooks/useRemote'
import { ConflictCard } from './ConflictCard'

/** On a record's page: what of this record's changes the authority did not take,
 * with the choices right there. Nothing while there is nothing to review. */
export function RecordConflicts({ recordId }: { recordId: string }) {
  const conflicts = useConflictsAbout(recordId)
  if (conflicts.length === 0) return null
  const n = conflicts.length
  return (
    <section
      aria-label="Changes not applied"
      className="mb-4 space-y-3 rounded-lg border border-attention-muted bg-attention-subtle p-3"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium text-attention">
          {n === 1
            ? '1 of your changes to this record was not applied'
            : `${n} of your changes to this record were not applied`}
        </h2>
        <Link to="/sync/review" className="text-xs">
          Review everything
        </Link>
      </div>
      <p className="text-xs text-fg-muted">
        The other side’s values were kept; yours are saved here until you
        choose. Nothing is lost either way.
      </p>
      {conflicts.map((c) => (
        <ConflictCard key={c.id} conflict={c} hideRecord />
      ))}
    </section>
  )
}
