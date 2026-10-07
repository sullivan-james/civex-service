/** The operating system's own folder dialog, in the desktop app only
 * (`useIsDesktop`). In a browser there is no such thing for a server-side
 * path: a page can't learn the real path of a folder the user picks, so the
 * in-app folder browser is used instead. */
export async function browseFolderDesktop(): Promise<string | null> {
  if (!window.pywebview) return null
  const r = await window.pywebview.api.browse_folder()
  return r.path ?? null
}
