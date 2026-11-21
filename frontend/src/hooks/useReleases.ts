import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import {
  releasesApi,
  type ReleaseCreateBody,
  type ReleaseMetadata,
  type ReleaseScopeBody,
} from '../api/releases'

export function useReleases() {
  return useQuery({ queryKey: ['releases'], queryFn: releasesApi.list })
}

export function useRelease(name: string) {
  return useQuery({
    queryKey: ['releases', name],
    queryFn: () => releasesApi.get(name),
    enabled: !!name,
  })
}

/** What a release of this scope would hold, from the catalog. */
export function useReleasePlan(body: ReleaseScopeBody, enabled = true) {
  return useQuery({
    queryKey: ['release-plan', body],
    queryFn: () => releasesApi.plan(body),
    enabled,
    placeholderData: keepPreviousData,
  })
}

/** How a release with these details would be cited, asked again as they
 * change (the caller debounces). */
export function useCitationPreview(
  body: ReleaseMetadata & { name: string },
  enabled = true,
) {
  return useQuery({
    queryKey: ['release-citation-preview', body],
    queryFn: () => releasesApi.preview(body),
    enabled,
    placeholderData: keepPreviousData,
  })
}

/** What yanking would give up (asked when the dialog opens). */
export function useYankPlan(name: string) {
  return useQuery({
    queryKey: ['releases', name, 'yank-plan'],
    queryFn: () => releasesApi.planYank(name),
    enabled: !!name,
  })
}

/** Where the release's files are, and whether a zip of them is allowed. */
export function useReleaseFilePlan(name: string, enabled = true) {
  return useQuery({
    queryKey: ['releases', name, 'files'],
    queryFn: () => releasesApi.filePlan(name),
    enabled: !!name && enabled,
  })
}

export function useReleaseCitation(name: string) {
  return useQuery({
    queryKey: ['releases', name, 'citation'],
    queryFn: () => releasesApi.citation(name),
    enabled: !!name,
  })
}

export function useReleaseChanges(name: string) {
  return useQuery({
    queryKey: ['releases', name, 'changes'],
    queryFn: () => releasesApi.changes(name),
    enabled: !!name,
  })
}

export function useCreateRelease() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ReleaseCreateBody) => releasesApi.create(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['releases'] }),
  })
}

export function useCorrectRelease(name: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ReleaseMetadata) => releasesApi.correct(name, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['releases'] }),
  })
}

export function useWithdrawRelease(name: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (reason: string) => releasesApi.withdraw(name, reason),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['releases'] }),
  })
}

export function useYankRelease(name: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (reason: string) => releasesApi.yank(name, reason),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['releases'] })
      void qc.invalidateQueries({ queryKey: ['store'] })
    },
  })
}

export function useVerifyRelease(name: string) {
  return useMutation({ mutationFn: () => releasesApi.verify(name) })
}
