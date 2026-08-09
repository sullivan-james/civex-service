import { IconButton } from './IconButton'
import { Select } from './Select'
import { ChevronLeft, ChevronRight } from './icons'

export const DEFAULT_PAGE_SIZES = [25, 50, 100]

interface PaginationProps {
  page: number
  pageSize: number
  total: number
  onPage: (page: number) => void
  onPageSize: (pageSize: number) => void
  pageSizes?: number[]
}

export function Pagination({
  page,
  pageSize,
  total,
  onPage,
  onPageSize,
  pageSizes = DEFAULT_PAGE_SIZES,
}: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const from = total === 0 ? 0 : page * pageSize + 1
  const to = Math.min((page + 1) * pageSize, total)

  return (
    <div className="flex items-center justify-between mt-4 text-sm text-fg-muted">
      <span aria-live="polite">
        {total === 0 ? 'No results' : `${from}–${to} of ${total}`}
      </span>
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-2 text-xs">
          Rows
          <Select
            size="sm"
            value={pageSize}
            onChange={(e) => {
              onPageSize(Number(e.target.value))
              onPage(0)
            }}
          >
            {pageSizes.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
        </label>
        <div className="flex items-center gap-1">
          <IconButton
            icon={ChevronLeft}
            aria-label="Previous page"
            onClick={() => onPage(page - 1)}
            disabled={page === 0}
          />
          <span className="px-2 text-xs">
            {page + 1} / {totalPages}
          </span>
          <IconButton
            icon={ChevronRight}
            aria-label="Next page"
            onClick={() => onPage(page + 1)}
            disabled={page >= totalPages - 1}
          />
        </div>
      </div>
    </div>
  )
}
