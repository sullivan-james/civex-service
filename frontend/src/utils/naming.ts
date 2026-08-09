/**
 * Slug names vs. human labels — the frontend half of `civex/domain/naming.py`.
 *
 * `name` is the machine key: what workflow YAML, CSV headers and
 * display_fields reference. `label` is free text for humans, and may be
 * null — always render it through `displayLabel`.
 *
 * Keep SLUG_RE in sync with SLUG_RE in civex/domain/naming.py; the server
 * rejects anything this lets through, so a drift shows up as a 422 the form
 * didn't predict.
 */

export const SLUG_RE = /^[a-z_][a-z0-9_]*$/

export const MAX_NAME_LENGTH = 255

export function isSlug(name: string): boolean {
  return name.length > 0 && name.length <= MAX_NAME_LENGTH && SLUG_RE.test(name)
}

/** Best-effort machine key derived from a human label. */
export function slugify(text: string): string {
  const asciiOnly = text
    .normalize('NFKD')
    // Strip combining marks left behind by NFKD (é → e + ́ → e).
    .replace(/[̀-ͯ]/g, '')
  const slug = asciiOnly
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
  if (!slug) return ''
  const prefixed = /^[0-9]/.test(slug) ? `_${slug}` : slug
  return prefixed.slice(0, MAX_NAME_LENGTH)
}

/** What a human should see: the explicit label, else a readable name. */
export function displayLabel(
  name: string,
  label?: string | null | undefined,
): string {
  if (label) return label
  const derived = name
    .replace(/_/g, ' ')
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase())
  return derived || name
}

/**
 * Validation message for a name typed into a form, or null if it's fine.
 * Mirrors the server's error so the user sees it before submitting.
 */
export function nameError(name: string): string | null {
  if (!name.trim()) return 'A name is required'
  if (name.length > MAX_NAME_LENGTH)
    return `Name is too long (max ${MAX_NAME_LENGTH} characters)`
  if (!SLUG_RE.test(name))
    return 'Use lowercase letters, digits and underscores only, not starting with a digit'
  return null
}
