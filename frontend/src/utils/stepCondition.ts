/**
 * A step's `if:` as the builder edits it: one test of one earlier output
 * ("only when the number of rows is more than 0"). The server's language
 * (`workflows/conditions.py`) is richer (and/or, several tests); anything the
 * builder can't show as one test stays as the expression it is.
 */

export type ConditionOp =
  'set' | 'unset' | '==' | '!=' | '>' | '<' | '>=' | '<='

export interface SimpleCondition {
  ref: string
  op: ConditionOp
  /** What it is compared with, as typed ('' for set/unset). */
  value: string
}

export const CONDITION_OPS: { value: ConditionOp; label: string }[] = [
  { value: 'set', label: 'has a value' },
  { value: 'unset', label: 'is empty' },
  { value: '==', label: 'is' },
  { value: '!=', label: 'is not' },
  { value: '>', label: 'is more than' },
  { value: '<', label: 'is less than' },
  { value: '>=', label: 'is at least' },
  { value: '<=', label: 'is at most' },
]

// A step id in an `if:` must be a plain name: `a-b.c` reads as a minus.
const REF = String.raw`[A-Za-z_]\w*\.[A-Za-z_]\w*`

function literalText(raw: string): string | null {
  const t = raw.trim()
  if (/^-?\d+(\.\d+)?$/.test(t)) return t
  if (t === 'True') return 'true'
  if (t === 'False') return 'false'
  const quoted = t.match(/^'(.*)'$|^"(.*)"$/)
  if (quoted) return quoted[1] ?? quoted[2] ?? ''
  return null
}

/** The one test `expr` is, or null when it isn't one (or is blank). */
export function readCondition(expr: string): SimpleCondition | null {
  const e = expr.trim()
  let m = e.match(new RegExp(`^(${REF})$`))
  if (m) return { ref: m[1], op: 'set', value: '' }
  m = e.match(new RegExp(`^not\\s+(${REF})$`))
  if (m) return { ref: m[1], op: 'unset', value: '' }
  m = e.match(new RegExp(`^(${REF})\\s*(==|!=|>=|<=|>|<)\\s*(.+)$`))
  if (m) {
    const value = literalText(m[3])
    if (value === null) return null
    return { ref: m[1], op: m[2] as ConditionOp, value }
  }
  return null
}

function literal(value: string): string {
  const t = value.trim()
  if (/^-?\d+(\.\d+)?$/.test(t)) return t
  if (t.toLowerCase() === 'true') return 'True'
  if (t.toLowerCase() === 'false') return 'False'
  return JSON.stringify(value)
}

export function writeCondition(c: SimpleCondition): string {
  if (!c.ref) return ''
  if (c.op === 'set') return c.ref
  if (c.op === 'unset') return `not ${c.ref}`
  return `${c.ref} ${c.op} ${literal(c.value)}`
}
