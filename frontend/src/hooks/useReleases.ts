import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import {
  releasesApi,
  type ComparedKind,
  type ReleaseMetadata,
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

/** The release compared with the data now. Inline for a typical release; a
 * large one (`compare_in_background`) waits for `compareRelease`, whose job
 * puts its answer here. Any record edit refreshes it (keyed under records). */
export function useReleaseComparison(name: string, enabled: boolean) {
  return useQuery({
    queryKey: ['records', 'release-compare', name],
    queryFn: () => releasesApi.compare(name),
    enabled: !!name && enabled,
  })
}

export function useComparedRecords(
  name: string,
  kind: ComparedKind | null,
  page: number,
  pageSize: number,
  collection?: string,
) {
  return useQuery({
    queryKey: [
      'records',
      'release-compare',
      name,
      kind,
      collection ?? null,
      page,
      pageSize,
    ],
    queryFn: () =>
      releasesApi.comparedRecords(
        name,
        kind as ComparedKind,
        page * pageSize,
        pageSize,
        collection,
      ),
    enabled: !!name && !!kind,
    placeholderData: keepPreviousData,
  })
}

export function useRecordDifferences(name: string, id: string | null) {
  return useQuery({
    queryKey: ['records', 'release-compare', name, 'record', id],
    queryFn: () => releasesApi.recordDifferences(name, id as string),
    enabled: !!name && !!id,
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
