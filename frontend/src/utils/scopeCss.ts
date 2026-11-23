/** civex's stylesheet, made to live inside a shadow root (`embed.tsx`).
 *
 * A shadow root keeps the app's styles in and the page's out, but a few things
 * written for a whole document need saying differently:
 *  - `:root` (where the tokens live) is the shadow host, `:host`;
 *  - `@property` registrations are ignored inside a shadow root, and without
 *    them Tailwind's `--tw-*` variables inherit where they must not, so they
 *    are returned apart, to register once on the page (they are only `--tw-*`
 *    names, which Tailwind gives the same meaning everywhere). */
export function scopeCss(css: string): { scoped: string; properties: string } {
  const properties: string[] = []
  const withoutProperties = css.replace(/@property[^{]*\{[^}]*\}/g, (rule) => {
    properties.push(rule)
    return ''
  })
  const scoped = withoutProperties
    .replace(/:root:not\((\[[^\]]+\])\)/g, ':host(:not($1))')
    .replace(/:root(\[[^\]]+\])/g, ':host($1)')
    .replace(/:root\b/g, ':host')
  return { scoped, properties: properties.join('\n') }
}
