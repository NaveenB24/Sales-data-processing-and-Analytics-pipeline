import { Button } from './Button'
import { rangeLabel } from '../lib/format'

export interface PaginationProps {
  offset: number
  limit: number
  total: number
  shown: number
  noun?: string
  onChange: (nextOffset: number) => void
  disabled?: boolean
}

export function Pagination({
  offset,
  limit,
  total,
  shown,
  noun = 'rows',
  onChange,
  disabled = false,
}: PaginationProps) {
  const page = Math.floor(offset / limit) + 1
  const pages = Math.max(1, Math.ceil(total / limit))
  const canPrev = offset > 0
  const canNext = offset + limit < total

  return (
    <nav className="pagination" aria-label={`${noun} pagination`}>
      <span className="num">{rangeLabel(offset, shown, total, noun)}</span>
      <div className="pagination__pages">
        <Button
          size="sm"
          onClick={() => onChange(Math.max(0, offset - limit))}
          disabled={disabled || !canPrev}
        >
          Previous
        </Button>
        <span className="num" aria-live="polite">
          Page {page} of {pages}
        </span>
        <Button
          size="sm"
          onClick={() => onChange(offset + limit)}
          disabled={disabled || !canNext}
        >
          Next
        </Button>
      </div>
    </nav>
  )
}
