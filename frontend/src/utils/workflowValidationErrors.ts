// PUT /workflows/{stem} reports contract violations as structured, per-step
// issues (WorkflowService.validate / validate_workflow_contracts, CIVEX-109)
// rather than a flat string, so the editor can group them by step and jump
// to the offending step instead of showing one opaque blob of text. Each
// issue's `message` still carries a redundant "Step '<id>'" / "Step id
// '<id>'" prefix (mirroring the `step` field) -- stripped here since the
// group header already names the step.

const STEP_PREFIX_RE = /^Step (?:id )?'([^']+)'\s*/

export interface WorkflowValidationIssue {
  step: string | null
  message: string
}

/** Issues grouped by step, in order of first appearance; `null` (general,
 * not tied to a step) comes wherever it was first seen among the issues. */
export function groupWorkflowValidationErrors(
  issues: WorkflowValidationIssue[],
): Array<{ step: string | null; messages: string[] }> {
  const groups: Array<{ step: string | null; messages: string[] }> = []
  const byStep = new Map<string | null, string[]>()
  for (const { step, message } of issues) {
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
