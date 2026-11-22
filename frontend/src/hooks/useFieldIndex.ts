import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  indexesApi,
  type FieldIndex,
  type FieldIndexReport,
} from '../api/indexes'

const key = (schema: string, field: string) => ['field-index', schema, field]

/** A field's index; polled while it is being built, so "Building…" turns into
 * done without a reload. */
export function useFieldIndex(schema: string, field: string, enabled = true) {
  return useQuery({
    queryKey: key(schema, field),
    queryFn: () => indexesApi.get(schema, field),
    enabled,
    refetchInterval: (q) => {
      const d = q.state.data as FieldIndex | undefined
      return d && d.indexed !== d.built ? 2000 : false
    },
  })
}

export function useSetFieldIndex(schema: string, field: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (indexed: boolean) => indexesApi.set(schema, field, indexed),
    onSuccess: (data) => {
      qc.setQueryData(key(schema, field), data)
      // The status bar shows the build that has just been asked for.
      void qc.invalidateQueries({ queryKey: REPORT_KEY })
    },
  })
}

export const REPORT_KEY = ['db-indexes']

/** Every field index and the build going on in the background: read often
 * while one is being built or waited for (a bar moves), rarely otherwise. */
export function useIndexReport(enabled = true) {
  return useQuery({
    queryKey: REPORT_KEY,
    queryFn: indexesApi.report,
    enabled,
    refetchInterval: (q) => {
      const d = q.state.data as FieldIndexReport | undefined
      return d && (d.building || d.elsewhere || !d.in_step) ? 2000 : 60_000
    },
  })
}
