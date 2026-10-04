/** A small tag naming the collection a record comes from. Shown only for
 * records outside the one being viewed -- i.e. ones from a global
 * collection -- so a reader can tell shared reference data from their own. */
export function CollectionMarker({ name }: { name: string }) {
  return (
    <span
      title={`From the "${name}" collection`}
      className="ml-1.5 rounded-md border border-border px-1 align-middle text-xs font-medium text-fg-muted"
    >
      {name}
    </span>
  )
}
