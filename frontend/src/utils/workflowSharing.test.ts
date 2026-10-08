import { describe, expect, it } from 'vitest'
import type { LibraryItem } from '../api/remote'
import type { Workflow } from '../api/workflows'
import {
  sharingLabel,
  sharingState,
  shows,
  workflowRows,
} from './workflowSharing'

const wf = (stem: string): Workflow => ({
  name: stem,
  description: null,
  steps: 2,
  filename: `${stem}.yaml`,
  stem,
  record_schema: null,
  inputs: null,
  runs_on: [],
})

const shared = (
  name: string,
  over: Partial<LibraryItem> = {},
): LibraryItem => ({
  kind: 'workflow',
  name,
  filename: `${name}.yaml`,
  sha256: 'a'.repeat(64),
  size: 1,
  version: 3,
  title: `Title of ${name}`,
  description: null,
  provides: null,
  needs: [],
  pins: {},
  triggers: ['record_created on encounter'],
  published_by: 'laptop',
  published_at: null,
  history: [],
  here: 'absent',
  local_version: null,
  missing: [],
  content: null,
  ...over,
})

describe('workflow sharing', () => {
  const rows = workflowRows(
    [wf('mine'), wf('same'), wf('behind'), wf('edited')],
    [
      shared('same', { here: 'same', local_version: 3 }),
      shared('behind', { here: 'older', local_version: 1 }),
      shared('edited', { here: 'different' }),
      shared('theirs'),
      { ...shared('a_plugin'), kind: 'plugin' },
    ],
  )
  const by = Object.fromEntries(rows.map((r) => [r.stem, r]))

  it('lists this project and the library as one, without plugins', () => {
    expect(rows.map((r) => r.stem)).toEqual([
      'mine',
      'same',
      'behind',
      'edited',
      'theirs',
    ])
    expect(by.theirs.name).toBe('Title of theirs')
    expect(by.theirs.triggers).toEqual(['record_created on encounter'])
  })

  it('says how each stands with the library', () => {
    expect(rows.map(sharingState)).toEqual([
      'not-shared',
      'shared',
      'update',
      'changed',
      'library',
    ])
    expect(sharingLabel(by.behind).label).toBe('v1 here · v3 available')
    expect(sharingLabel(by.same).label).toBe('Shared · v3')
  })

  it('filters by that', () => {
    const pick = (show: string) =>
      rows.filter((r) => shows(r, show)).map((r) => r.stem)
    expect(pick('here')).toEqual(['mine', 'same', 'behind', 'edited'])
    expect(pick('shared')).toEqual(['same', 'behind', 'edited'])
    expect(pick('update')).toEqual(['behind'])
    expect(pick('library')).toEqual(['theirs'])
  })
})
