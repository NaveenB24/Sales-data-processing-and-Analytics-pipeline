/**
 * Paginated explorer over `GET /api/jobs/{id}/rows` with a status filter and a
 * debounced free-text search. Validation failures are rendered as code chips so
 * the reason a row was rejected is readable at a glance.
 */

import { useEffect, useId, useState } from 'react'

import { api } from '../api/client'
import type { RowStatusFilter, Transaction } from '../api/types'
import { useAsync } from '../hooks/useAsync'
import {
  formatCurrency,
  formatDate,
  formatNumber,
  formatPercent,
} from '../lib/format'
import { Button } from './Button'
import { EmptyState, ErrorState } from './EmptyState'
import { Pagination } from './Pagination'
import { SkeletonRows } from './Spinner'
import { RowStatusPill } from './StatusPill'
import { DataTable, TableWrap, Td, Th } from './Table'
import { SearchIcon } from './icons'

const PAGE_SIZE = 25
const SEARCH_DEBOUNCE_MS = 300

const STATUS_OPTIONS: Array<{ value: RowStatusFilter; label: string }> = [
  { value: 'all', label: 'All rows' },
  { value: 'valid', label: 'Valid' },
  { value: 'invalid', label: 'Invalid' },
  { value: 'duplicate', label: 'Duplicate' },
]

export function RowExplorer({ jobId }: { jobId: string }) {
  const statusId = useId()
  const searchId = useId()

  const [status, setStatus] = useState<RowStatusFilter>('all')
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [offset, setOffset] = useState(0)

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(search.trim())
      setOffset(0)
    }, SEARCH_DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [search])

  const rows = useAsync(
    (signal) =>
      api.jobs.rows(jobId, { status, limit: PAGE_SIZE, offset, q: debounced }, signal),
    [jobId, status, offset, debounced],
  )

  const items = rows.data?.items ?? []
  const total = rows.data?.total ?? 0

  return (
    <section className="card" aria-labelledby="rows-title">
      <header className="card__header">
        <div>
          <h2 className="card__title" id="rows-title">
            Row explorer
          </h2>
          <p className="card__desc">Every parsed row, with its validation outcome.</p>
        </div>
        <div className="card__actions">
          <div className="toolbar">
            <div className="field">
              <label className="field__label" htmlFor={statusId}>
                Show
              </label>
              <select
                id={statusId}
                className="select"
                value={status}
                onChange={(event) => {
                  setStatus(event.target.value as RowStatusFilter)
                  setOffset(0)
                }}
              >
                {STATUS_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field search">
              <label className="field__label visually-hidden" htmlFor={searchId}>
                Search rows
              </label>
              <input
                id={searchId}
                className="input"
                type="search"
                value={search}
                placeholder="Search id, region, category…"
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
            <Button
              size="sm"
              onClick={rows.reload}
              loading={rows.loading && !rows.initial}
              icon={<SearchIcon size={13} />}
            >
              Refresh
            </Button>
          </div>
        </div>
      </header>

      <div className="card__body card__body--flush">
        {rows.loading && rows.initial ? (
          <SkeletonRows rows={6} />
        ) : rows.error ? (
          <ErrorState title="Could not load rows" message={rows.error} onRetry={rows.reload} />
        ) : items.length === 0 ? (
          <EmptyState
            title="No rows match"
            body={
              debounced || status !== 'all'
                ? 'Clear the search box or switch the status filter to see more rows.'
                : 'This job has not produced any rows yet. Process it first.'
            }
            action={
              debounced || status !== 'all' ? (
                <Button
                  size="sm"
                  onClick={() => {
                    setSearch('')
                    setStatus('all')
                    setOffset(0)
                  }}
                >
                  Clear filters
                </Button>
              ) : null
            }
          />
        ) : (
          <>
            <TableWrap label="Job rows">
              <DataTable
                caption={`Rows ${status === 'all' ? '' : `filtered to ${status} `}for this job`}
                head={
                  <>
                    <Th numeric>#</Th>
                    <Th>Transaction</Th>
                    <Th>Status</Th>
                    <Th>Region</Th>
                    <Th>Category</Th>
                    <Th numeric>Qty</Th>
                    <Th numeric>Unit price</Th>
                    <Th numeric>Discount</Th>
                    <Th>Date</Th>
                    <Th numeric>Net</Th>
                    <Th>Issues</Th>
                  </>
                }
              >
                {items.map((row) => (
                  <RowLine key={row.id} row={row} />
                ))}
              </DataTable>
            </TableWrap>
            <Pagination
              offset={offset}
              limit={PAGE_SIZE}
              total={total}
              shown={items.length}
              noun="rows"
              onChange={setOffset}
              disabled={rows.loading}
            />
          </>
        )}
      </div>
    </section>
  )
}

function RowLine({ row }: { row: Transaction }) {
  return (
    <tr>
      <Td numeric>{row.row_number}</Td>
      <Td>
        <span className="mono">{row.transaction_id ?? '—'}</span>
      </Td>
      <Td>
        <RowStatusPill status={row.status} />
      </Td>
      <Td>{row.region ?? '—'}</Td>
      <Td>{row.product_category ?? '—'}</Td>
      <Td numeric>{formatNumber(row.quantity)}</Td>
      <Td numeric>{formatCurrency(row.unit_price)}</Td>
      <Td numeric>{formatPercent(row.discount_percent)}</Td>
      <Td>{formatDate(row.transaction_date)}</Td>
      <Td numeric>{formatCurrency(row.net_amount)}</Td>
      <Td wrap>
        {row.errors.length === 0 ? (
          <span className="faint">—</span>
        ) : (
          <ul className="chip-list">
            {row.errors.map((error, index) => (
              <li key={`${error.code}-${error.field ?? index}`}>
                <span
                  className="chip"
                  title={`${error.field ? `${error.field}: ` : ''}${error.message}`}
                >
                  {error.code}
                  {error.field ? ` · ${error.field}` : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Td>
    </tr>
  )
}
