import type { ReactNode } from 'react'
import { TimeZoneContext } from './timeZoneContext'

/** Provides a collection's timezone to the datetime fields beneath it. */
export function CollectionTimeZone({
  timeZone,
  children,
}: {
  timeZone: string | null | undefined
  children: ReactNode
}) {
  return (
    <TimeZoneContext.Provider value={timeZone ?? null}>
      {children}
    </TimeZoneContext.Provider>
  )
}
