import { createContext, useContext } from 'react'

/** The collection a file being uploaded belongs to. It only steers which
 * volume receives new content (the collection's home volume, if it has one) --
 * content that already exists is reused wherever it lives. Provided once by a
 * page that knows its collection, so the file inputs underneath don't each need
 * the id passed down. */
export const UploadCollectionContext = createContext<string | undefined>(
  undefined,
)

export function useUploadCollection(): string | undefined {
  return useContext(UploadCollectionContext)
}
