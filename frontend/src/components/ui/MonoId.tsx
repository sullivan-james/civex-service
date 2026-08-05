export function MonoId({ id, length = 8 }: { id: string; length?: number }) {
  return (
    <span className="font-mono text-xs text-fg-muted" title={id}>
      {id.slice(0, length)}
    </span>
  )
}
