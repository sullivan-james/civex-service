import { Navigate, useParams } from 'react-router'
import { schemaRecordsPath } from '../utils/explorerState'

/** Saved views used to have their own builder page; they now open in the
 * records explorer. Keeps old links and bookmarks working. */
export default function ViewRedirect() {
  const { id, viewName } = useParams<{ id: string; viewName?: string }>()
  return (
    <Navigate
      replace
      to={schemaRecordsPath(
        id!,
        viewName && viewName !== 'new' ? viewName : undefined,
      )}
    />
  )
}
