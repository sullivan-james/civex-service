import type { LibraryItem } from '../api/remote'
import type { Workflow } from '../api/workflows'

/** One row of the workflows list: a workflow in this project, one in the
 * library, or both (the same name). */
export interface WorkflowRow {
  stem: string
  name: string
  description: string | null
  steps: number | null
  triggers: string[]
  /** Here, in this project; null if only in the library. */
  local: Workflow | null
  /** In the library (its newest version); null if not shared. */
  shared: LibraryItem | null
}

/** How a workflow stands with the library, as one word: the one rule the
 * list, its filter and the workflow's page all read. */
export type SharingState =
  | 'not-shared' // here, not in the library
  | 'shared' // here, the library's newest version
  | 'update' // here as an earlier library version: a newer one waits
  | 'changed' // here, changed since (matches no version): publish it
  | 'library' // in the library, not installed here

/** A workflow's own page (in this project, or only in the library). */
export const workflowHref = (stem: string) =>
  `/workflows/${encodeURIComponent(stem)}`

export function workflowRows(
  local: Workflow[],
  library: LibraryItem[],
): WorkflowRow[] {
  const shared = new Map(
    library.filter((i) => i.kind === 'workflow').map((i) => [i.name, i]),
  )
  const rows: WorkflowRow[] = local.map((wf) => ({
    stem: wf.stem,
    name: wf.name,
    description: wf.description,
    steps: wf.steps,
    triggers: wf.runs_on ?? [],
    local: wf,
    shared: shared.get(wf.stem) ?? null,
  }))
  const here = new Set(local.map((wf) => wf.stem))
  for (const item of shared.values()) {
    if (here.has(item.name)) continue
    rows.push({
      stem: item.name,
      name: item.title ?? item.name,
      description: item.description,
      steps: null,
      triggers: item.triggers,
      local: null,
      shared: item,
    })
  }
  return rows
}

export function sharingState(row: WorkflowRow): SharingState {
  if (!row.local) return 'library'
  if (!row.shared) return 'not-shared'
  if (row.shared.here === 'same') return 'shared'
  if (row.shared.here === 'older') return 'update'
  return 'changed'
}

export function sharingLabel(row: WorkflowRow): {
  label: string
  variant: 'default' | 'success' | 'attention' | 'accent'
} {
  const v = row.shared?.version
  switch (sharingState(row)) {
    case 'not-shared':
      return { label: 'Not shared', variant: 'default' }
    case 'shared':
      return { label: `Shared · v${v}`, variant: 'success' }
    case 'update':
      return {
        label: `v${row.shared?.local_version} here · v${v} available`,
        variant: 'attention',
      }
    case 'changed':
      return { label: `Changed here · shared v${v}`, variant: 'attention' }
    case 'library':
      return { label: `In the library · v${v}`, variant: 'accent' }
  }
}

/** The "Show…" choices of the list, by state. */
export const SHOW_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'Show…' },
  { value: 'here', label: 'In this project' },
  { value: 'shared', label: 'Shared' },
  { value: 'not-shared', label: 'Not shared' },
  { value: 'update', label: 'Update available' },
  { value: 'changed', label: 'Changed here' },
  { value: 'library', label: 'Not installed here' },
]

export function shows(row: WorkflowRow, show: string): boolean {
  if (!show) return true
  const state = sharingState(row)
  if (show === 'here') return state !== 'library'
  if (show === 'shared') return state !== 'not-shared' && state !== 'library'
  return state === show
}
