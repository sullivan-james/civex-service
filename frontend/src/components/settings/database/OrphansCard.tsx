import { Link } from 'react-router'
import type { Orphan } from '../../../api/records'
import { useOrphans, useRestoreAbove } from '../../../hooks/useRestore'
import { Button, Card, Skeleton } from '../../ui'

/** Live records that sit under a deleted record: out of sight, and refused by
 * a sync server. Each can be put back in place (its deleted parents restored,
 * each by itself) here, or opened to delete it instead. Shown only when there
 * are any. */
export function OrphansCard() {
  const { data, isLoading } = useOrphans()
  if (isLoading) return <Skeleton className="h-24 w-full" />
  if (!data?.total || !data.items) return null
  return (
    <Card
      title="Records under a deleted record"
      count={data.total}
      info="Nothing above lists them, and a sync server won't take them. Restore what each sits under, or open it and delete it."
    >
      <ul className="divide-y divide-border-muted">
        {data.items.map((o) => (
          <OrphanRow key={o.record.id} orphan={o} />
        ))}
      </ul>
      {data.total > data.items.length && (
        <p className="mt-2 text-xs text-fg-muted">
          And {(data.total - data.items.length).toLocaleString()} more.
        </p>
      )}
    </Card>
  )
}

function OrphanRow({ orphan: o }: { orphan: Orphan }) {
  const restore = useRestoreAbove()
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
      <span className="min-w-0">
        <Link
          to={`/records/${o.record.id}`}
          className="font-medium text-accent hover:underline"
        >
          {o.record.schema_name} {o.record.natural_name ?? ''}
        </Link>
        <span className="text-fg-muted">
          {' '}
          under deleted{' '}
          {o.above
            .map((a) => `${a.schema_name} ${a.natural_name ?? ''}`.trim())
            .join(' › ')}
          {o.collection ? ` · ${o.collection}` : ''}
        </span>
      </span>
      <Button
        size="sm"
        disabled={restore.isPending}
        onClick={() => restore.mutate(o.record.id)}
      >
        Restore what it sits under
      </Button>
    </li>
  )
}
