import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { bucketApi, type BucketSettings } from '../api/bucket'

const KEY = ['store', 'bucket']

/** Where this project's files are kept: a bucket, or drives. */
export function useBucket() {
  return useQuery({ queryKey: KEY, queryFn: bucketApi.get })
}

/** Tries a bucket without using it. */
export function useCheckBucket() {
  return useMutation({
    mutationFn: (body: BucketSettings) => bucketApi.check(body),
  })
}

/** Switching between drives and a bucket changes what the server offers
 * (`features`) and where every file is, so everything is asked again. */
function useRefreshEverything() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries()
}

export function useUseBucket() {
  const refresh = useRefreshEverything()
  return useMutation({
    mutationFn: (body: BucketSettings) => bucketApi.use(body),
    onSuccess: refresh,
  })
}

export function useStopUsingBucket() {
  const refresh = useRefreshEverything()
  return useMutation({
    mutationFn: () => bucketApi.stopUsing(),
    onSuccess: refresh,
  })
}
