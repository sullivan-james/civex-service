import type { ReactNode } from 'react'
import { useFeatures } from '../hooks/useFeatures'
import { useRemoteStatus } from '../hooks/useRemote'
import { offered, type Feature } from '../utils/features'
import { EmptyState, Page } from './ui'
import { LoadingState } from './ui/States'

/** What a page says when this server (or this project) doesn't do what it is
 * for: reached by an address typed or bookmarked, since the nav already hides
 * it. */
export function NotAvailable({ what }: { what?: string }) {
  return (
    <Page title="Not available here">
      <EmptyState
        title="Not available here"
        message={what ?? 'This page isn’t part of what this server offers.'}
      />
    </Page>
  )
}

/** A route's page, only where the server offers `feature` (all of them, if
 * several). Until the server has answered, a local civex is assumed
 * (`useFeatures`), so a page doesn't flash "not available" on load. */
export function Gated({
  feature,
  children,
}: {
  feature: Feature | readonly Feature[]
  children: ReactNode
}) {
  const features = useFeatures()
  return offered(features, { feature }) ? children : <NotAvailable />
}

/** A page about following another civex, only for a project that does: not a
 * hosted authority, and not one that follows nothing. */
export function GatedFollowsRemote({ children }: { children: ReactNode }) {
  const { data, isLoading } = useRemoteStatus()
  if (isLoading) return <LoadingState />
  if (!data?.configured || data.serving)
    return (
      <NotAvailable what="This project doesn’t follow another civex, so there is nothing to sync." />
    )
  return children
}
