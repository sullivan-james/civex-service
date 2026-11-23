import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { recordsApi } from '../../api/records'
import { recordSyncText } from '../../utils/recordSync'

export default function RecordSyncBadge({ recordId }: { recordId: string }) {
  const { data } = useQuery({
    queryKey: ['record-sync', recordId],
    queryFn: () => recordsApi.sync(recordId),
    refetchInterval: 5000,
    retry: false,
  })
  const text = data ? recordSyncText(data) : null
  if (!data || !text) return null
  const needsReview = data.state === 'refused' || data.state === 'conflict'
  const tone = needsReview
    ? 'text-danger'
    : data.state === 'synced'
      ? 'text-fg-muted'
      : 'text-warning'
  return (
    <p className={`text-xs ${tone}`} data-testid="record-sync">
      {text}
      {needsReview && (
        <>
          {' · '}
          <Link className="underline" to="/sync/review">
            Review
          </Link>
        </>
      )}
    </p>
  )
}
