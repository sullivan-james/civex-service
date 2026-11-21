import type { ReleaseAuthor } from '../../api/releases'
import { Button, Field, IconButton, Input } from '../ui'
import { Plus, Trash2 } from '../ui/icons'

/** A release's authors, in citation order: a name each, and an ORCID and an
 * affiliation when they have them. */
export function AuthorsField({
  authors,
  onChange,
}: {
  authors: ReleaseAuthor[]
  onChange: (next: ReleaseAuthor[]) => void
}) {
  const setAuthor = (i: number, patch: Partial<ReleaseAuthor>) =>
    onChange(authors.map((a, j) => (j === i ? { ...a, ...patch } : a)))
  return (
    <fieldset className="space-y-2">
      <legend className="mb-1 text-sm font-medium text-fg">Authors</legend>
      {authors.map((a, i) => (
        <div
          key={i}
          className="grid grid-cols-[1fr_11rem_1fr_auto] items-end gap-2"
        >
          <Field label="Name" hideLabel={i > 0}>
            <Input
              value={a.name}
              placeholder="Ada Lovelace"
              onChange={(e) => setAuthor(i, { name: e.target.value })}
            />
          </Field>
          <Field
            label="ORCID"
            hideLabel={i > 0}
            info="e.g. 0000-0002-1825-0097"
          >
            <Input
              value={a.orcid ?? ''}
              placeholder="0000-0000-0000-0000"
              onChange={(e) => setAuthor(i, { orcid: e.target.value })}
            />
          </Field>
          <Field label="Affiliation" hideLabel={i > 0}>
            <Input
              value={a.affiliation ?? ''}
              onChange={(e) => setAuthor(i, { affiliation: e.target.value })}
            />
          </Field>
          <IconButton
            icon={Trash2}
            variant="subtle"
            aria-label={`Remove author ${i + 1}`}
            disabled={authors.length === 1}
            onClick={() => onChange(authors.filter((_, j) => j !== i))}
          />
        </div>
      ))}
      <Button size="sm" onClick={() => onChange([...authors, { name: '' }])}>
        <Plus className="h-4 w-4" aria-hidden="true" /> Add author
      </Button>
    </fieldset>
  )
}
