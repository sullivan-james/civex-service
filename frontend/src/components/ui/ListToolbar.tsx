import { useEffect, useState } from 'react'
import { Field } from './Field'
import { Input } from './Input'
import { Select } from './Select'

export interface ListPick {
  label: string
  value: string
  /** `''` is "any"; list it first. */
  options: { value: string; label: string }[]
  onChange: (value: string) => void
}

/** The controls over a simple list: a search box and a few dropdowns. */
export function ListToolbar({
  search,
  picks = [],
}: {
  search?: { value: string; label: string; onChange: (q: string) => void }
  picks?: ListPick[]
}) {
  const committed = search?.value ?? ''
  const [text, setText] = useState(committed)
  const [seen, setSeen] = useState(committed)
  // Follow the address when it changes from outside (Back, a cleared link).
  if (committed !== seen) {
    setSeen(committed)
    setText(committed)
  }
  useEffect(() => {
    if (!search || text === committed) return
    const t = setTimeout(() => search.onChange(text), 300)
    return () => clearTimeout(t)
  }, [text, committed, search])

  return (
    <div className="flex flex-wrap items-center gap-2">
      {search && (
        <div className="min-w-[14rem] max-w-md flex-1">
          <Field label={search.label} hideLabel>
            <Input
              type="search"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={search.label}
              className="w-full"
            />
          </Field>
        </div>
      )}
      {picks.map((p) => (
        <Field key={p.label} label={p.label} hideLabel>
          <Select
            value={p.value}
            onChange={(e) => p.onChange(e.target.value)}
            aria-label={p.label}
          >
            {p.options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.value === '' ? p.label : o.label}
              </option>
            ))}
          </Select>
        </Field>
      ))}
    </div>
  )
}
