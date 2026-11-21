import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { indexesApi, type FieldIndex } from '../api/indexes'

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
    onSuccess: (data) => qc.setQueryData(key(schema, field), data),
  })
}
