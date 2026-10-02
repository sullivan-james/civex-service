/** Whether this is the desktop app, which has the operating system's own
 * folder dialog. In a browser there is no such thing for a server-side path: a
 * page can't learn the real path of a folder the user picks, so the in-app
 * folder browser is used instead. */
export const isDesktop = typeof window !== 'undefined' && !!window.pywebview

export async function browseFolderDesktop(): Promise<string | null> {
  if (!window.pywebview) return null
  const r = await window.pywebview.api.browse_folder()
  return r.path ?? null
}
