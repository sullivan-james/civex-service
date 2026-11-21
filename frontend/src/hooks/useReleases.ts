import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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

/** What a release of this scope would hold: the bundle's own plan. */
export function useReleasePlan(body: ReleaseScopeBody, enabled = true) {
  return useQuery({
    queryKey: ['release-plan', body],
    queryFn: () => releasesApi.plan(body),
    enabled,
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

export function useVerifyRelease(name: string) {
  return useMutation({ mutationFn: () => releasesApi.verify(name) })
}
