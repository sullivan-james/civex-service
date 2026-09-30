import type { ReactNode } from 'react'
import { WithHierarchy } from '../explorer/HierarchySidebar'
import { useSchemas } from '../../hooks/useSchemas'
import { displayLabel } from '../../utils/naming'
import { Page } from '../ui'
import { recordTrail } from '../../utils/recordTrail'

/** What a page about a record shares: the collection's hierarchy beside it,
 * the breadcrumb down to it, then its title and description. */
export function RecordPageFrame({
  collection,
  collectionId,
  recordId,
  path,
  current,
  currentSchema,
  title,
  description,
  children,
}: {
  /** Collection name, once loaded. */
  collection: string | undefined
  collectionId: string
  /** The record the page is about; absent for a not-yet-created one. */
  recordId?: string
  /** Records above this page, root first. */
  path: {
    id: string
    natural_name: string | null
    schema_name: string
  }[]
  /** Label of the page itself, the last crumb. */
  current: string
  /** Schema name of the page's own record, shown beside the last crumb. */
  currentSchema?: string
  title: ReactNode
  description?: ReactNode
  children: ReactNode
}) {
  const { data: schemas } = useSchemas()
  const schemaLabel = (name: string) => {
    const s = schemas?.find((x) => x.name === name)
    return displayLabel(name, s?.label)
  }
  return (
    <WithHierarchy
      dataset={collection}
      collectionId={collectionId}
      recordId={recordId}
    >
      <Page
        breadcrumbs={[
          ...recordTrail(
            collection ? { name: collection, id: collectionId } : undefined,
            path,
            schemaLabel,
          ),
          {
            label: current,
            kind: currentSchema ? schemaLabel(currentSchema) : undefined,
          },
        ]}
        title={title}
        description={description}
      >
        {children}
      </Page>
    </WithHierarchy>
  )
}
