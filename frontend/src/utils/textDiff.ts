/** Word-level difference between two texts, for showing what changed inside a
 * value the way a merge editor does: each side keeps its own text and marks the
 * parts the other side does not have. */

export interface Seg {
  text: string
  changed: boolean
}

// Words, runs of white space, and single punctuation marks: small enough to point
// at the change, big enough to read.
const TOKENS = /\s+|[\p{L}\p{N}_]+|[^\s\p{L}\p{N}_]/gu

/** Past this many token pairs a diff is not worth waiting for: show both sides
 * whole instead. */
const LIMIT = 4_000_000

function tokens(text: string): string[] {
  return text.match(TOKENS) ?? []
}

function join(parts: Seg[]): Seg[] {
  const out: Seg[] = []
  for (const p of parts) {
    const last = out[out.length - 1]
    if (last && last.changed === p.changed) last.text += p.text
    else out.push({ ...p })
  }
  return out
}

/** Each side's text cut into pieces, marking what the other side lacks; null when
 * the texts are too big to compare (or there is nothing to compare). */
export function diffText(
  a: string,
  b: string,
): { left: Seg[]; right: Seg[] } | null {
  const x = tokens(a)
  const y = tokens(b)
  if (x.length * y.length > LIMIT) return null
  // Longest common subsequence of tokens, by the usual table.
  const w = y.length + 1
  const table = new Uint32Array((x.length + 1) * w)
  for (let i = x.length - 1; i >= 0; i--)
    for (let j = y.length - 1; j >= 0; j--)
      table[i * w + j] =
        x[i] === y[j]
          ? table[(i + 1) * w + j + 1] + 1
          : Math.max(table[(i + 1) * w + j], table[i * w + j + 1])
  const left: Seg[] = []
  const right: Seg[] = []
  let i = 0
  let j = 0
  while (i < x.length && j < y.length) {
    if (x[i] === y[j]) {
      left.push({ text: x[i], changed: false })
      right.push({ text: y[j], changed: false })
      i++
      j++
    } else if (table[(i + 1) * w + j] >= table[i * w + j + 1]) {
      left.push({ text: x[i++], changed: true })
    } else {
      right.push({ text: y[j++], changed: true })
    }
  }
  while (i < x.length) left.push({ text: x[i++], changed: true })
  while (j < y.length) right.push({ text: y[j++], changed: true })
  return { left: join(left), right: join(right) }
}

/** For two lists of simple values (tags, choices): each item with whether the
 * other list lacks it. */
export function diffItems(
  a: unknown[],
  b: unknown[],
): {
  left: { item: unknown; changed: boolean }[]
  right: { item: unknown; changed: boolean }[]
} {
  const key = (v: unknown) => JSON.stringify(v)
  const inA = new Set(a.map(key))
  const inB = new Set(b.map(key))
  return {
    left: a.map((item) => ({ item, changed: !inB.has(key(item)) })),
    right: b.map((item) => ({ item, changed: !inA.has(key(item)) })),
  }
}
