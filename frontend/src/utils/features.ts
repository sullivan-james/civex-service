/** What a server does, said once: the names in `domain/features.py`. The app
 * hides what the server it talks to doesn't do; a project in a folder on this
 * machine does all of these, which is what is assumed until the server has
 * answered, so nothing flickers on load. */
export const LOCAL_FEATURES = [
  'volumes',
  'store_admin',
  'local_workflows',
  'plugin_editor',
  'terminal',
  'db_admin',
  'updates',
  'logs',
  'ai',
  'open_folder',
  'desktop',
  'settings',
  'settings_appearance',
  'settings_retention',
  'settings_map',
  'settings_advanced',
  'settings_devices',
  'settings_members',
] as const

export type Feature = (typeof LOCAL_FEATURES)[number] | string

export type FeatureSet = ReadonlySet<string>

export const localFeatures: FeatureSet = new Set<string>(LOCAL_FEATURES)

/** Whether `item` applies on a server with `features`: items that name no
 * feature always do. */
export function offered(
  features: FeatureSet,
  item: { feature?: Feature | readonly Feature[] },
): boolean {
  if (item.feature === undefined) return true
  const needed = Array.isArray(item.feature) ? item.feature : [item.feature]
  return needed.every((f) => featureOn(features, f))
}

const SETTINGS_SECTIONS = [
  'settings_appearance',
  'settings_retention',
  'settings_map',
  'settings_advanced',
  'settings_devices',
  'settings_members',
]

/** One feature on a server: a settings section is off whenever the `settings`
 * umbrella is (`domain/features.py` `enabled`, the same rule). */
export function featureOn(features: FeatureSet, feature: Feature): boolean {
  if (SETTINGS_SECTIONS.includes(feature) && !features.has('settings'))
    return false
  return features.has(feature)
}

/** What each Settings section needs, by its address under `/settings`: the
 * nav and the route both read this, so a section a host turned off is neither
 * listed nor reachable. (Sync has none here: a hosted project's Devices
 * section asks for `settings_devices` itself.) */
export const SETTINGS_SECTION_FEATURES: Record<string, string | string[]> = {
  appearance: 'settings_appearance',
  database: 'db_admin',
  storage: 'store_admin',
  retention: 'settings_retention',
  members: ['accounts', 'settings_members'],
  map: 'settings_map',
  updates: 'updates',
  logs: 'logs',
  advanced: 'settings_advanced',
}
