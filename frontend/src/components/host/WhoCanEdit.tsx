import { Users } from 'lucide-react'
import { useHasFeature } from '../../hooks/useFeatures'
import { useAccount, usePermissions } from '../../hooks/useMe'
import { Button } from '../ui'

/** The page of the host's where members of this project are managed,
 * narrowed to one collection (`?collection=<id>`). */
function manageCollectionUrl(manage: string, collectionId: string) {
  const url = new URL(manage, window.location.href)
  url.searchParams.set('collection', collectionId)
  return url.toString()
}

/** Under a host with accounts, a collection's header says whether this person
 * may change it, and links to who may, on the host's members page. A local
 * civex has neither, and this draws nothing. */
export function WhoCanEdit({ collectionId }: { collectionId: string }) {
  const has = useHasFeature()
  const { manage_url: manage } = useAccount()
  const { can, why } = usePermissions()
  if (!has('accounts') || !manage) return null
  const viewOnly = !can('write_records', collectionId)
  return (
    <Button
      href={manageCollectionUrl(manage, collectionId)}
      title={viewOnly ? why('write_records') : 'Who may change this collection'}
    >
      <Users size={14} aria-hidden="true" />
      {viewOnly ? 'View only' : 'Who can edit'}
    </Button>
  )
}
