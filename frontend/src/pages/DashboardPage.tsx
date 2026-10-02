import { useCallback, useState } from 'react'

import { api } from '../api/client'
import type { JobStatusFilter } from '../api/types'
import { useAsync } from '../hooks/useAsync'
import { Card } from '../components/Card'
import { ErrorState } from '../components/EmptyState'
import { JobsTable } from '../components/JobsTable'
import { SkeletonRows } from '../components/Spinner'
import { StatTile } from '../components/StatTile'
import { UploadCard } from '../components/UploadCard'
import { useAuth } from '../auth/AuthContext'
import {
  formatCurrency,
  formatNumber,
  formatPercent,
} from '../lib/format'

const PAGE_SIZE = 10

export default function DashboardPage() {
  const { user } = useAuth()
  const [status, setStatus] = useState<JobStatusFilter>('all')
  const [offset, setOffset] = useState(0)

  const jobs = useAsync(
    (signal) => api.jobs.list({ limit: PAGE_SIZE, offset, status }, signal),
    [offset, status],
  )
  const overview = useAsync((signal) => api.reports.overview(signal), [])

  const refreshAll = useCallback(() => {
    jobs.reload()
    overview.reload()
  }, [jobs, overview])

  const changeStatus = useCallback((next: JobStatusFilter) => {
    setStatus(next)
    setOffset(0)
  }, [])

  return (
    <div className="stack">
      <div className="page-head">
        <div className="page-head__title">
          <h1>Dashboard</h1>
          <p className="page-head__sub">
            Signed in as {user?.email}. Upload transaction files, watch them process, and read the
            numbers across every job.
          </p>
        </div>
      </div>

      <div className="grid grid--upload">
        <UploadCard onUploaded={refreshAll} />

        <Card
          title="Across all your jobs"
          description="Totals from every completed run."
          labelledBy="overview-title"
          flush={overview.loading && overview.initial}
        >
          {overview.loading && overview.initial ? (
            <SkeletonRows rows={3} />
          ) : overview.error ? (
            <ErrorState
              title="Overview unavailable"
              message={overview.error}
              onRetry={overview.reload}
            />
          ) : overview.data ? (
            <div className="grid grid--tiles">
              <StatTile
                label="Total revenue"
                value={formatCurrency(overview.data.total_revenue)}
                tone="accent"
                compact
                hint={`Discounts: ${formatCurrency(overview.data.discount_impact)}`}
              />
              <StatTile
                label="Rows processed"
                value={formatNumber(overview.data.rows_processed)}
                hint={`${formatNumber(overview.data.completed_jobs)} of ${formatNumber(
                  overview.data.jobs_total,
                )} jobs completed`}
              />
              <StatTile
                label="Top region"
                value={overview.data.by_region[0]?.key ?? '—'}
                compact
                hint={
                  overview.data.by_region[0]
                    ? `${formatCurrency(overview.data.by_region[0].revenue)} · ${formatPercent(
                        overview.data.by_region[0].share_pct,
                      )} share`
                    : 'No regional data yet'
                }
              />
              <StatTile
                label="Top category"
                value={overview.data.by_category[0]?.key ?? '—'}
                compact
                hint={
                  overview.data.by_category[0]
                    ? `${formatCurrency(overview.data.by_category[0].revenue)} · ${formatPercent(
                        overview.data.by_category[0].share_pct,
                      )} share`
                    : 'No category data yet'
                }
              />
            </div>
          ) : (
            <p className="muted">No cross-job figures yet.</p>
          )}
        </Card>
      </div>

      <JobsTable
        jobs={jobs.data?.items ?? []}
        total={jobs.data?.total ?? 0}
        offset={offset}
        limit={PAGE_SIZE}
        status={status}
        loading={jobs.loading}
        initialLoad={jobs.initial}
        error={jobs.error}
        onStatusChange={changeStatus}
        onOffsetChange={setOffset}
        onRefresh={refreshAll}
      />
    </div>
  )
}
