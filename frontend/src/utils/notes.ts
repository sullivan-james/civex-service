import type { FilterableField } from './hierarchy'
import type { FilterConditionWire, FilterTreeWire } from './filterTree'

/** The filter tree's and the explorer's name for whether a record has threads
 * of notes not yet resolved (a field's name can't start with `@`, so it never
 * shadows one). Mirrors `civex.domain.notes`. */
export const OPEN_NOTES_FILTER = '@open_notes'
/** What the filter chips call the record itself, in place of a schema. */
const RECORD = 'record'

/** "Has open notes" as a field of the filter builder, so the explorer
 * filters by it with its own controls. */
export function noteFilterFields(): FilterableField[] {
  return [
    {
      id: 'record-open-notes',
      name: OPEN_NOTES_FILTER,
      label: 'Has open notes',
      type: 'boolean',
      restrictions: {},
      operators: ['eq'],
      required: false,
      default: null,
      position: null,
      sourceSchemaName: RECORD,
      relation: 'self' as const,
      ownerless: true,
    },
  ] as FilterableField[]
}

const OPEN: FilterTreeWire = { field: OPEN_NOTES_FILTER, op: 'eq', value: true }

/** Every record with an open thread, across every collection: the
 * Collections page's All records, filtered. The one place to see what is
 * open; the same list for everyone. */
export function openNotesHref(): string {
  return `/collections?tab=records&filter=${encodeURIComponent(JSON.stringify(OPEN))}`
}

/** Whether a filter asks for records with open threads (anywhere in an
 * AND; an OR may not). */
export function asksForOpenNotes(filter: FilterTreeWire | null): boolean {
  if (!filter) return false
  if ('and' in filter) return (filter.and ?? []).some(asksForOpenNotes)
  if ('or' in filter) return false
  const leaf = filter as FilterConditionWire
  return leaf.field === OPEN_NOTES_FILTER && leaf.value === true
}

/** How a list shows a record's open threads: how many, and the latest's
 * first line. */
export function openNotesText(
  open: number | null | undefined,
  latest: string | null | undefined,
): string | null {
  if (!open) return null
  const count = `${open} open`
  return latest ? `${count} · ${latest}` : count
}
