/** Licences data is commonly released under, by SPDX id
 * (https://spdx.org/licenses/), offered as a release's licence. Anything else
 * may be typed: a licence is free text, and an SPDX id is what tools read. */
export const SPDX_LICENCES: { id: string; name: string }[] = [
  { id: 'CC-BY-4.0', name: 'Creative Commons Attribution 4.0' },
  { id: 'CC-BY-SA-4.0', name: 'Creative Commons Attribution Share Alike 4.0' },
  {
    id: 'CC-BY-NC-4.0',
    name: 'Creative Commons Attribution Non Commercial 4.0',
  },
  {
    id: 'CC-BY-NC-SA-4.0',
    name: 'Creative Commons Attribution Non Commercial Share Alike 4.0',
  },
  {
    id: 'CC-BY-ND-4.0',
    name: 'Creative Commons Attribution No Derivatives 4.0',
  },
  {
    id: 'CC-BY-NC-ND-4.0',
    name: 'Creative Commons Attribution Non Commercial No Derivatives 4.0',
  },
  { id: 'CC0-1.0', name: 'Creative Commons Zero 1.0 (public domain)' },
  { id: 'ODbL-1.0', name: 'Open Data Commons Open Database License 1.0' },
  { id: 'ODC-By-1.0', name: 'Open Data Commons Attribution License 1.0' },
  { id: 'PDDL-1.0', name: 'Open Data Commons Public Domain Dedication 1.0' },
  { id: 'OGL-UK-3.0', name: 'Open Government Licence v3.0 (UK)' },
  {
    id: 'CDLA-Permissive-2.0',
    name: 'Community Data License Agreement Permissive 2.0',
  },
  { id: 'MIT', name: 'MIT License' },
  { id: 'Apache-2.0', name: 'Apache License 2.0' },
  { id: 'GPL-3.0-or-later', name: 'GNU General Public License v3.0 or later' },
]

/** The licence's name when it is a known SPDX id. */
export function licenceName(id: string | null | undefined): string | null {
  if (!id) return null
  const wanted = id.trim().toLowerCase()
  return SPDX_LICENCES.find((l) => l.id.toLowerCase() === wanted)?.name ?? null
}
