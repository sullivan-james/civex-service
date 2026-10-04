/**
 * Every field `type` the backend accepts. Single source of truth on the
 * frontend — mirrors `VALID_DTYPES` in `src/civex/services/schema_service.py`
 * (that Python set is the actual authority; this is kept in sync with it by
 * hand, since nothing here is fetched from the API). Anywhere on the
 * frontend that needs "all field types" or "is this a known type" should
 * import from here rather than re-declaring its own list — that's exactly
 * what let `FieldForm.tsx`'s copy silently drift out of a single source of
 * truth before this file existed.
 */
export const FIELD_TYPES = [
  'string',
  'integer',
  'float',
  'boolean',
  'date',
  'datetime',
  'file',
  'file_list',
  'reference',
  'reference_list',
  'enum',
  'url',
  'tags',
  'geo',
  'longtext',
] as const

export type FieldType = (typeof FIELD_TYPES)[number]
