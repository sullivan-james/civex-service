import GCPanel from '../GCPanel'
import { TransfersTab } from './TransfersTab'
import type { TransferPreset } from './NewTransferModal'

/** Things Civex does to stored files: moving them between volumes, and
 * cleaning up ones nothing uses. */
export function TasksTab({ preset }: { preset?: TransferPreset }) {
  return (
    <div className="space-y-8">
      <section aria-labelledby="move-files" className="space-y-3">
        <h3 id="move-files" className="text-base font-semibold text-fg">
          Move files
        </h3>
        <TransfersTab preset={preset} />
      </section>
      <section aria-labelledby="clean-up">
        <GCPanel />
      </section>
    </div>
  )
}
