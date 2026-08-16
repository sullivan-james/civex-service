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

export function useAllViews() {
  return useQuery({ queryKey: ['views'], queryFn: viewsApi.listAll })
}

export function useViews(schemaName: string) {
  return useQuery({
    queryKey: ['views', schemaName],
    queryFn: () => viewsApi.list(schemaName),
    enabled: !!schemaName,
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
      qc.invalidateQueries({ queryKey: ['views', schemaName] })
      toast.success(`View "${created.name}" saved`)
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
      qc.invalidateQueries({ queryKey: ['views', schemaName] })
      toast.success(`View "${updated.name}" saved`)
    },
  })
}

export function useDeleteView(schemaName: string) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (viewName: string) => viewsApi.delete(schemaName, viewName),
    onSuccess: (_data, viewName) => {
      qc.invalidateQueries({ queryKey: ['views', schemaName] })
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
