import { describe, it, expect } from 'vitest'
import { describeStep } from './useAutomationTasks'
import type { RunStep } from '../../api/workflows'

const step = (over: Partial<RunStep> = {}): RunStep => ({
  job_id: 'j',
  workflow: 'tidy',
  step: 'parse',
  plugin: 'project.parse',
  done: null,
  total: null,
  message: '',
  ...over,
})

describe('describeStep', () => {
  it('names the step when the plugin has said nothing', () => {
    expect(describeStep(step())).toBe('Step parse')
  })

  it("gives the plugin's message and count", () => {
    expect(
      describeStep(step({ message: 'Reading sel_03.txt', done: 3, total: 12 })),
    ).toBe('parse: Reading sel_03.txt (3 of 12)')
  })

  it('gives a count with no total, or a message alone', () => {
    expect(describeStep(step({ done: 40 }))).toBe('parse: 40')
    expect(describeStep(step({ message: 'Uploading' }))).toBe(
      'parse: Uploading',
    )
  })
})
