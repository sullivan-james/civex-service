/** What a server does, said once: the names in `domain/features.py`. The app
 * hides what the server it talks to doesn't do; a project in a folder on this
 * machine does all of these, which is what is assumed until the server has
 * answered, so nothing flickers on load. */
export const LOCAL_FEATURES = [
  'volumes',
  'local_workflows',
  'plugin_editor',
  'terminal',
  'db_admin',
  'updates',
  'logs',
  'ai',
  'open_folder',
  'desktop',
] as const

export type Feature = (typeof LOCAL_FEATURES)[number] | string

export type FeatureSet = ReadonlySet<string>

export const localFeatures: FeatureSet = new Set<string>(LOCAL_FEATURES)

/** Whether `item` applies on a server with `features`: items that name no
 * feature always do. */
export function offered(
  features: FeatureSet,
  item: { feature?: Feature },
): boolean {
  return item.feature === undefined || features.has(item.feature)
}
