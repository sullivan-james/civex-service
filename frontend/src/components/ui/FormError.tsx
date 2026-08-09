/** Plain-language form-level error, with the raw backend detail available
 * behind a disclosure for support purposes — used wherever a mutation error
 * isn't (fully) attributable to a single field's `<Field error>`. */
export function FormError({
  message,
  technical,
}: {
  message: string | null
  technical?: string | null
}) {
  if (!message && !technical) return null
  return (
    <div className="text-xs text-danger space-y-1">
      {message && <p role="alert">{message}</p>}
      {technical && (
        <details>
          <summary className="cursor-pointer text-fg-subtle hover:underline">
            Technical details
          </summary>
          <pre className="mt-1 whitespace-pre-wrap font-mono text-fg-subtle">
            {technical}
          </pre>
        </details>
      )}
    </div>
  )
}
