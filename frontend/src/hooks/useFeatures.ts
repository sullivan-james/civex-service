import { useQuery } from '@tanstack/react-query'
import { featuresApi } from '../api/features'
import { localFeatures, offered, type FeatureSet } from '../utils/features'

function isHostedFiles(features: unknown): boolean {
  return (
    Array.isArray(features) &&
    features.includes('accounts') &&
    !features.includes('volumes')
  )
}

/** What the server last said, kept for a place that only needs it when
 * something goes wrong, like a failed download: a plain link then costs no
 * subscription or request of its own (the app asks once, at the start). */
let hostedFromServer = false
export const hostedFilesNow = () => hostedFromServer

/** What this server does (`GET /status/features`), as a set. Until it has
 * answered, everything a local civex does is assumed, so a page built for a
 * machine doesn't flicker; a host that does less narrows it once. */
function useFeaturesQuery() {
  return useQuery({
    queryKey: ['features'],
    queryFn: () =>
      featuresApi.get().then((answer) => {
        hostedFromServer = isHostedFiles(answer?.features)
        return answer
      }),
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

/** Whether files are kept by a host (a hub) rather than on drives this
 * computer manages: the host offers accounts and no drives. Then the app shows
 * no drive, volume or storage location, only whether a file is on the hub.
 * A local project, with or without a bucket, has no accounts and is
 * unchanged. */
export function useHostedFiles(): boolean {
  return isHostedFiles([...useFeatures()])
}
