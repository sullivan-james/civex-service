import { useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import type { FileSelection } from '../api/fileAccess'
import { ExportDialog, type MenuPreset } from '../components/files/ExportDialog'
import { FilesDialog } from '../components/files/FilesDialog'
import type { FlowContext, Problem } from '../components/files/fileFlows'
import { useToast } from '../components/ui'

/** Everything a place that offers exports needs: the flows' context and the two
 * dialogs they can open (the export dialog, and the one that asks what to do
 * about files that can't be reached). Menus and buttons that start an export both
 * use it, so there is one of each dialog however it is started. */
export function useExportHost({
  selection,
  folderName,
  scopeSchema,
}: {
  /** Where the export is being asked for. */
  selection: FileSelection
  folderName: string
  scopeSchema?: string
}): {
  ctx: FlowContext
  navigate: ReturnType<typeof useNavigate>
  /** Open the export dialog, for a saved export or (none) a one-time one. */
  openExport: (preset?: MenuPreset) => void
  dialogs: ReactNode
} {
  const toast = useToast()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [problem, setProblem] = useState<Problem | null>(null)
  const [exporting, setExporting] = useState<{ preset?: MenuPreset } | null>(
    null,
  )
  const ctx: FlowContext = { toast, qc, problem: setProblem }

  return {
    ctx,
    navigate,
    openExport: (preset) => setExporting({ preset }),
    dialogs: (
      <>
        {exporting && (
          <ExportDialog
            context={selection}
            folderName={folderName}
            scopeSchema={scopeSchema}
            preset={exporting.preset}
            ctx={ctx}
            onClose={() => setExporting(null)}
          />
        )}
        {problem && (
          <FilesDialog
            problem={problem}
            selection={selection}
            folderName={folderName}
            ctx={ctx}
            onClose={() => setProblem(null)}
          />
        )}
      </>
    ),
  }
}
