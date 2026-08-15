/**
 * Minimal RFC 4180 CSV parser for client-side preview and import. The real
 * parse that gets written to records happens server-side in
 * `civex.load_csv` (pandas) — this only has to be good enough to preview
 * columns/rows and drive the same row data the plugin would produce.
 */

export interface ParsedCsv {
  columns: string[]
  /** Each row keyed by column name, values as raw strings (no type coercion). */
  rows: Record<string, string>[]
}

/** Split CSV text into rows of raw string fields, honouring quoted fields
 * (which may contain commas, newlines, and escaped `""` quotes). */
function splitRows(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let inQuotes = false
  let i = 0
  const n = text.length

  function endField() {
    row.push(field)
    field = ''
  }
  function endRow() {
    endField()
    rows.push(row)
    row = []
  }

  while (i < n) {
    const c = text[i]
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"'
          i += 2
          continue
        }
        inQuotes = false
        i++
        continue
      }
      field += c
      i++
      continue
    }
    if (c === '"') {
      inQuotes = true
      i++
      continue
    }
    if (c === ',') {
      endField()
      i++
      continue
    }
    if (c === '\r') {
      i++
      continue
    }
    if (c === '\n') {
      endRow()
      i++
      continue
    }
    field += c
    i++
  }
  // Trailing field/row, unless the text ended cleanly on a newline.
  if (field.length > 0 || row.length > 0) endRow()

  return rows
}

export function parseCsv(text: string): ParsedCsv {
  const rows = splitRows(text).filter((r) => !(r.length === 1 && r[0] === ''))
  if (rows.length === 0) return { columns: [], rows: [] }
  const columns = rows[0]
  const dataRows = rows.slice(1).map((r) => {
    const obj: Record<string, string> = {}
    columns.forEach((col, idx) => {
      obj[col] = r[idx] ?? ''
    })
    return obj
  })
  return { columns, rows: dataRows }
}
