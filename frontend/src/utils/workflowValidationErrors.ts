// Save-time validation errors arrive as one message per line (see
// WorkflowService.validate / validate_workflow_contracts), each either
// prefixed with "Step '<id>'" / "Step id '<id>'" or, for stem/YAML-parse
// failures, unprefixed. Parsing that convention client-side lets the editor
// group errors by step and jump to the offending step instead of showing
// one opaque blob of text.

const STEP_PREFIX_RE = /^Step (?:id )?'([^']+)'\s*/

export interface WorkflowValidationIssue {
  step: string | null
  message: string
}

export function parseWorkflowValidationErrors(
  raw: string,
): WorkflowValidationIssue[] {
  return raw
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => ({
      step: line.match(STEP_PREFIX_RE)?.[1] ?? null,
      message: line,
    }))
}

/** Issues grouped by step, in order of first appearance; `null` (general,
 * not tied to a step) comes wherever it was first seen among the messages. */
export function groupWorkflowValidationErrors(
  raw: string,
): Array<{ step: string | null; messages: string[] }> {
  const groups: Array<{ step: string | null; messages: string[] }> = []
  const byStep = new Map<string | null, string[]>()
  for (const { step, message } of parseWorkflowValidationErrors(raw)) {
    let messages = byStep.get(step)
    if (!messages) {
      messages = []
      byStep.set(step, messages)
      groups.push({ step, messages })
    }
    messages.push(message.replace(STEP_PREFIX_RE, ''))
  }
  return groups
}

/** 1-based line number of a step's `id:` declaration in workflow YAML, or
 * null if the step can't be found — used to jump the editor to a failing
 * step. */
export function findStepLine(content: string, stepId: string): number | null {
  const escaped = stepId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const re = new RegExp(`^\\s*-?\\s*id:\\s*['"]?${escaped}['"]?\\s*$`)
  const lines = content.split('\n')
  for (let i = 0; i < lines.length; i++) {
    if (re.test(lines[i])) return i + 1
  }
  return null
}
