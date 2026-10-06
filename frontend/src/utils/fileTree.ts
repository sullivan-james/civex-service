/** One row of a folder tree, in display order: how deep, folder or file, and its
 * name. Folders also say how many files they hold; files may say how big they
 * are and whether they can be reached. */
export interface TreeRow {
  depth: number
  kind: 'folder' | 'file' | 'table'
  name: string
  /** Files in a folder, at any depth. */
  count?: number
  size?: number
  /** False for a file that can't be reached right now. */
  available?: boolean
  /** For a table the export writes: how many rows it will have. */
  rows?: number
}

interface Entry {
  path: string
  size?: number
  available?: boolean
  /** Set for a table the export writes (not a stored file): its row count. */
  rows?: number
}

interface Folder {
  folders: Map<string, Folder>
  files: { name: string; size?: number; available?: boolean; rows?: number }[]
  count: number
}

const newFolder = (): Folder => ({ folders: new Map(), files: [], count: 0 })

/** Paths ("A/B/c.txt") as the rows of the folder tree they make: folders before
 * files at each level, each in name order, folders carrying how many files they
 * hold. The one place a list of paths becomes a navigable structure. */
export function pathsToRows(entries: Entry[]): TreeRow[] {
  const root = newFolder()
  for (const e of entries) {
    const parts = e.path.split('/').filter(Boolean)
    const name = parts.pop()
    if (!name) continue
    let at = root
    at.count++
    for (const part of parts) {
      let next = at.folders.get(part)
      if (!next) {
        next = newFolder()
        at.folders.set(part, next)
      }
      next.count++
      at = next
    }
    at.files.push({
      name,
      size: e.size,
      available: e.available,
      rows: e.rows,
    })
  }

  const byName = (a: string, b: string) =>
    a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' })
  const rows: TreeRow[] = []
  const walk = (folder: Folder, depth: number) => {
    for (const name of [...folder.folders.keys()].sort(byName)) {
      const child = folder.folders.get(name)!
      rows.push({ depth, kind: 'folder', name, count: child.count })
      walk(child, depth + 1)
    }
    for (const f of [...folder.files].sort((a, b) => byName(a.name, b.name)))
      rows.push({ depth, kind: f.rows === undefined ? 'file' : 'table', ...f })
  }
  walk(root, 0)
  return rows
}

/** The rows that are showing, given the folders collapsed (by their index in
 * `rows`): everything under a collapsed folder is hidden, the folder itself is
 * not. */
export function visibleRows(
  rows: TreeRow[],
  collapsed: ReadonlySet<number>,
): { row: TreeRow; index: number }[] {
  const out: { row: TreeRow; index: number }[] = []
  let hideBelow: number | null = null
  rows.forEach((row, index) => {
    if (hideBelow !== null && row.depth > hideBelow) return
    hideBelow = null
    out.push({ row, index })
    if (row.kind === 'folder' && collapsed.has(index)) hideBelow = row.depth
  })
  return out
}
