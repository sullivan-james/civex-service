import { recordsApi, type RecordSelectionBody } from '../../api/records'
import type { Chart } from '../../api/schemas'
import { saveBlob } from '../files/fileFlows'
import { chartRequest } from '../../utils/chartFilter'

/** Download the numbers of one or more charts, a table file each (a map has
 * none): the same numbers each chart shows over `records`. */
export async function downloadCharts(
  charts: { chart: Chart; title: string }[],
  records: RecordSelectionBody,
  format: string,
): Promise<void> {
  for (const { chart, title } of charts) {
    const body = chartRequest(chart, records, true)
    if (!body) continue
    const got = await recordsApi.summaryFile(body, format)
    saveBlob(got.blob, `${title}.${format}`)
  }
}
