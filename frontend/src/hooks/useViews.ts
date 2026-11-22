import {
  useQuery,
  useMutation,
  useQueryClient,
  keepPreviousData,
} from '@tanstack/react-query'
import {
  viewsApi,
  type CreateViewBody,
  type UpdateViewBody,
  type PreviewViewBody,
} from '../api/views'
import { useToast } from '../components/ui/ToastProvider'
import { errorMessage } from '../lib/errors'

/** Everything a saved view shows up in: its schema's list, the palette's
 * every-filter list. */
function invalidateViews(
  qc: ReturnType<typeof useQueryClient>,
  schemaName: string,
) {
  qc.invalidateQueries({ queryKey: ['views', schemaName] })
  qc.invalidateQueries({ queryKey: ['all-views'] })
  qc.invalidateQueries({ queryKey: ['dashboard'] })
}

export function useViews(schemaName: string) {
  return useQuery({
    queryKey: ['views', schemaName],
    queryFn: () => viewsApi.list(schemaName),
    enabled: !!schemaName,
  })
}

/** Every saved view across every schema (the palette's filter search). */
export function useAllViews(enabled = true) {
  return useQuery({
    queryKey: ['all-views'],
    queryFn: viewsApi.listAll,
    enabled,
  })
}

export function useView(schemaName: string, viewName: string) {
  return useQuery({
    queryKey: ['views', schemaName, viewName],
    queryFn: () => viewsApi.get(schemaName, viewName),
    enabled: !!schemaName && !!viewName,
  })
}

export function useCreateView(schemaName: string) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (body: CreateViewBody) => viewsApi.create(schemaName, body),
    onSuccess: (created) => {
      invalidateViews(qc, schemaName)
      toast.success(`Filter “${created.name}” saved`)
    },
  })
}

export function useUpdateView(schemaName: string, viewName: string) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (body: UpdateViewBody) =>
      viewsApi.update(schemaName, viewName, body),
    onSuccess: (updated) => {
      invalidateViews(qc, schemaName)
      toast.success(`Filter “${updated.name}” saved`)
    },
  })
}

export function useDeleteView(schemaName: string) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (viewName: string) => viewsApi.delete(schemaName, viewName),
    onSuccess: (_data, viewName) => {
      invalidateViews(qc, schemaName)
      toast.success(`View "${viewName}" deleted`)
    },
    onError: (err) => toast.error(errorMessage(err)),
  })
}

/** Live preview for the current (possibly unsaved) column/filter/sort
 * selection. `keepPreviousData` avoids a loading flicker on every keystroke
 * while the caller debounces `request`. */
export function useViewPreview(
  schemaName: string,
  request: PreviewViewBody,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ['views', schemaName, 'preview', request],
    queryFn: () => viewsApi.preview(schemaName, request),
    enabled: enabled && !!schemaName,
    placeholderData: keepPreviousData,
  })
}
