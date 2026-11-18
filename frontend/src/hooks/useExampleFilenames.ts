import { useQuery } from '@tanstack/react-query'
import { recordsApi } from '../api/records'

/** How many records are looked at for names: the most `GET /records` gives. */
const LOOKED_AT = 100
const NONE: string[] = []

function namesIn(value: unknown): string[] {
  const refs = Array.isArray(value) ? value : [value]
  return refs.flatMap((ref) =>
    ref &&
    typeof ref === 'object' &&
    typeof (ref as { filename?: unknown }).filename === 'string'
      ? [(ref as { filename: string }).filename]
      : [],
  )
}

/** The names of the files already in `fieldName` on records of `schemaName`
 * (a `file` or `file_list` field), each once: examples to build a file-name
 * pattern from. Empty until both are given, or when there are none. */
export function useExampleFilenames(
  schemaName: string | null | undefined,
  fieldName: string | null | undefined,
): string[] {
  const { data } = useQuery({
    queryKey: ['records', 'example-filenames', schemaName, fieldName],
    queryFn: () =>
      recordsApi.searchBySchema(schemaName as string, undefined, LOOKED_AT),
    enabled: !!schemaName && !!fieldName,
    staleTime: 60_000,
    select: (records) => [
      ...new Set(records.flatMap((r) => namesIn(r.data[fieldName as string]))),
    ],
  })
  return data ?? NONE
}
