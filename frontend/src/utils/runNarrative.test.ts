import { describe, it, expect } from 'vitest'
import {
  causedBy,
  describeTrigger,
  explainFailure,
  pluginDisplayName,
  stepStory,
  summarizeRun,
} from './runNarrative'
import type { StepExecution, WorkflowJob } from '../api/workflows'
import type { PluginInfo } from '../api/plugins'

function makeJob(overrides: Partial<WorkflowJob> = {}): WorkflowJob {
  return {
    id: 'job-1',
    workflow_name: 'wf',
    record_id: 'rec-1',
    schema_name: 'Subject',
    trigger: 'record_created',
    status: 'completed',
    error: null,
    error_details: null,
    log: null,
    step_executions: null,
    affected_records: null,
    created_at: '2026-01-01T00:00:00Z',
    started_at: '2026-01-01T00:00:00Z',
    finished_at: '2026-01-01T00:00:01Z',
    depth: 0,
    trigger_detail: null,
    ...overrides,
  }
}

function makeStep(overrides: Partial<StepExecution> = {}): StepExecution {
  return {
    step_id: 's1',
    plugin: 'civex.match_files_to_records',
    status: 'success',
    inputs: {},
    outputs: {},
    duration_seconds: 1,
    error: null,
    depends_on: [],
    ...overrides,
  }
}

describe('describeTrigger', () => {
  it('describes an automatic create trigger in plain language', () => {
    expect(describeTrigger(makeJob({ trigger: 'record_created' }))).toContain(
      'created',
    )
  })

  it('describes a manual run', () => {
    expect(describeTrigger(makeJob({ trigger: 'manual' }))).toContain(
      'Run manually',
    )
  })
})

describe('describeTrigger with the field that changed', () => {
  const updated = (changes: object[], caused_by = null) =>
    makeJob({
      trigger: 'record_updated',
      trigger_detail: { changes, caused_by } as WorkflowJob['trigger_detail'],
    })

  it('names the one field that started the run', () => {
    const job = updated([
      { field: 'contour_file', before: 'a.csv', after: 'b.csv', watched: true },
    ])
    expect(describeTrigger(job)).toBe(
      'Triggered automatically because contour_file was updated on this Subject record.',
    )
  })

  it('names several, and only the ones the workflow watches', () => {
    const job = updated([
      { field: 'a', before: null, after: '1', watched: true },
      { field: 'b', before: null, after: '2', watched: true },
      { field: 'c', before: null, after: '3', watched: false },
    ])
    expect(describeTrigger(job)).toContain('a and b were updated')
    expect(describeTrigger(job)).not.toMatch(/\bc\b/)
  })

  it('falls back to the plain sentence for a run that predates this', () => {
    expect(describeTrigger(makeJob({ trigger: 'record_updated' }))).toBe(
      'Triggered automatically when this Subject record was updated.',
    )
  })

  it('reports the run behind a chained one', () => {
    expect(
      causedBy(updated([], { job_id: 'j0', workflow: 'wf0' } as never)),
    ).toEqual({ job_id: 'j0', workflow: 'wf0' })
    expect(causedBy(makeJob())).toBeNull()
  })
})

describe('summarizeRun', () => {
  it('groups affected records by schema and action', () => {
    const job = makeJob({
      affected_records: [
        {
          record_id: '1',
          schema_name: 'Sample',
          natural_name: 'a',
          action: 'created',
        },
        {
          record_id: '2',
          schema_name: 'Sample',
          natural_name: 'b',
          action: 'created',
        },
        {
          record_id: '3',
          schema_name: 'File',
          natural_name: 'c',
          action: 'updated',
        },
      ],
    })

    expect(summarizeRun(job)).toEqual([
      '2 Sample records created',
      '1 File record updated',
    ])
  })

  it('adds skipped/unmatched counts from step outputs', () => {
    const job = makeJob({
      affected_records: [],
      step_executions: [
        makeStep({ outputs: { created: 3, skipped: 2 } }),
        makeStep({ outputs: { unmatched: ['a.csv', 'b.csv'] } }),
      ],
    })

    expect(summarizeRun(job)).toEqual(['2 skipped', '2 unmatched'])
  })

  it('returns an empty list when nothing happened', () => {
    expect(summarizeRun(makeJob())).toEqual([])
  })
})

describe('stepStory', () => {
  it('describes a skipped step', () => {
    expect(stepStory(makeStep({ status: 'skipped' }))).toMatch(/Skipped/)
  })

  it('describes a failed step that still consumed input', () => {
    const step = makeStep({ status: 'failed', inputs: { files: [1, 2, 3] } })
    expect(stepStory(step)).toBe('Took 3 files in, then failed.')
  })

  it('narrates input and output counts together', () => {
    const step = makeStep({
      inputs: { files: [1, 2, 3, 4] },
      outputs: { created: 3, updated: 1 },
    })
    expect(stepStory(step)).toBe('Took 4 files in → 3 created, 1 updated.')
  })
})

describe('explainFailure', () => {
  it('falls back to generic guidance for an unknown error kind', () => {
    const result = explainFailure({
      kind: 'something_new',
      message: 'x',
      retryable: false,
      step: null,
    })
    expect(result.headline).toBe('This run failed.')
  })

  it('gives specific guidance for a known error kind', () => {
    const result = explainFailure({
      kind: 'validation_error',
      message: 'x',
      retryable: false,
      step: 'step-1',
    })
    expect(result.headline).toMatch(/validation/)
    expect(result.step).toBe('step-1')
  })

  it('handles a null error_details', () => {
    expect(explainFailure(null).headline).toBe('This run failed.')
  })
})

describe('pluginDisplayName', () => {
  it('resolves a display name from the plugin list', () => {
    const plugins: PluginInfo[] = [
      {
        id: 'civex.parse_table',
        name: 'Parse Table',
        description: '',
        builtin: true,
        category: 'inputs',
        capabilities: [],
        inputs: null,
        outputs: null,
        config_schema: {},
        filename: null,
      },
    ]
    expect(pluginDisplayName('civex.parse_table', plugins)).toBe('Parse Table')
  })

  it('falls back to the raw id when the plugin is unknown', () => {
    expect(pluginDisplayName('civex.mystery', [])).toBe('civex.mystery')
    expect(pluginDisplayName('civex.mystery', undefined)).toBe('civex.mystery')
  })
})
