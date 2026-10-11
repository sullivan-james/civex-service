import { useQuery } from '@tanstack/react-query'
import { featuresApi } from '../api/features'
import { localFeatures, offered, type FeatureSet } from '../utils/features'

/** What this server does (`GET /status/features`), as a set. Until it has
 * answered, everything a local civex does is assumed, so a page built for a
 * machine doesn't flicker; a host that does less narrows it once. */
export function useFeatures(): FeatureSet {
  const { data } = useQuery({
    queryKey: ['features'],
    queryFn: featuresApi.get,
    staleTime: Infinity,
  })
  return data ? new Set(data.features) : localFeatures
}

/** `has('volumes')`: whether this server offers a feature. */
export function useHasFeature(): (feature: string) => boolean {
  const features = useFeatures()
  return (feature) => offered(features, { feature })
}
