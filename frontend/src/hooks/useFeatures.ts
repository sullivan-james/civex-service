import { useQuery } from '@tanstack/react-query'
import { featuresApi } from '../api/features'
import { localFeatures, offered, type FeatureSet } from '../utils/features'

/** What this server does (`GET /status/features`), as a set. Until it has
 * answered, everything a local civex does is assumed, so a page built for a
 * machine doesn't flicker; a host that does less narrows it once. */
function useFeaturesQuery() {
  return useQuery({
    queryKey: ['features'],
    queryFn: featuresApi.get,
    staleTime: Infinity,
  })
}

/** Whether the server has said what it does (or failed to): a choice made on
 * the assumed local features, like where to redirect, waits for it. */
export function useFeaturesSettled(): boolean {
  return !useFeaturesQuery().isPending
}

export function useFeatures(): FeatureSet {
  const { data } = useFeaturesQuery()
  // An answer without the list (an older server, a stub) is no answer.
  return Array.isArray(data?.features) ? new Set(data.features) : localFeatures
}

/** `has('volumes')`: whether this server offers a feature. */
export function useHasFeature(): (feature: string) => boolean {
  const features = useFeatures()
  return (feature) => offered(features, { feature })
}
