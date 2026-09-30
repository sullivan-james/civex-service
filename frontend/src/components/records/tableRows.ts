import type { CivexRecord } from '../../api/records'
import type { RecordsTableRow } from './RecordsTable'

/** A page of records as table rows: values the record's own data can't
 * answer (inherited fields, `ref.field` joins) come from `derived`. */
export function toTableRows(items: CivexRecord[]): RecordsTableRow[] {
  return items.map((r) => ({ ...r, data: { ...r.derived, ...r.data } }))
}
