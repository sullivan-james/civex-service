import type { ReactNode } from 'react'
import { CollectionNameContext, TimeZoneContext } from './timeZoneContext'

/** Provides a collection's timezone and name to the fields beneath it. */
export function CollectionTimeZone({
  timeZone,
  collection,
  children,
}: {
  timeZone: string | null | undefined
  collection?: string | null
  children: ReactNode
}) {
  return (
    <TimeZoneContext.Provider value={timeZone ?? null}>
      <CollectionNameContext.Provider value={collection ?? null}>
        {children}
      </CollectionNameContext.Provider>
    </TimeZoneContext.Provider>
  )
}
