import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { schemasApi } from '../api/schemas'
import { useDebouncedValue } from './useDebouncedValue'

/** What a `from_filename` rule's patterns make of a file name, asked of the
 * server as the person types (the one implementation of the patterns):
 * each pattern's problem, and the value `filename` gives. Off while
 * `enabled` is false or there are no patterns. */
export function useFromFilenamePreview(
  filename: string,
  patterns: string[],
  kind: string,
  enabled = true,
) {
  const body = useDebouncedValue({ filename, patterns, kind }, 300)
  return useQuery({
    queryKey: ['from-filename-preview', body],
    queryFn: () => schemasApi.previewFromFilename(body),
    enabled: enabled && body.patterns.length > 0,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  })
}
