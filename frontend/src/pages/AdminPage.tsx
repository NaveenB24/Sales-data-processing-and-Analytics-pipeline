import { Link } from 'react-router-dom'

import { api } from '../api/client'
import type { Job, JobList, SystemMetricsOut, User } from '../api/types'
import { useAsync } from '../hooks/useAsync'
import { Card } from '../components/Card'
import { EmptyState, ErrorState } from '../components/EmptyState'
import { SkeletonRows } from '../components/Spinner'
import { StatTile } from '../components/StatTile'
import { RolePill, StatusPill, jobStatusLabel } from '../components/StatusPill'
import { DataTable, TableWrap, Td, Th } from '../components/Table'
import type { JobStatus } from '../api/types'
import {
  formatDateTime,
  formatDuration,
  formatNumber,
  formatPercent,
  formatRelative,
  formatUptime,
  shortId,
} from '../lib/format'

const STATUS_ORDER: JobStatus[] = ['pending', 'queued', 'processing', 'completed', 'failed']

export default function AdminPage() {
  const metrics = useAsync((signal) => api.metrics(signal), [])
  const users = useAsync((signal) => api.admin.users(signal), [])
  const jobs = useAsync((signal) => api.admin.jobs(signal), [])

  const jobItems = normaliseJobs(jobs.data)

  return (
    <div className="stack">
      <div className="page-head">
        <div className="page-head__title">
          <h1>Administration</h1>
          <p className="page-head__sub">
            System health, registered accounts and every processing job across all users.
          </p>
        </div>
      </div>

      <Card
        title="System metrics"
        description="Live counters from the processing service."
        labelledBy="metrics-title"
        actions={
          <button type="button" className="btn btn--sm" onClick={metrics.reload}>
            Refresh
          </button>
        }
      >
        {metrics.loading && metrics.initial ? (
          <SkeletonRows rows={3} />
        ) : metrics.error ? (
          <ErrorState
            title="Metrics unavailable"
            message={metrics.error}
            onRetry={metrics.reload}
          />
        ) : metrics.data ? (
          <MetricsTiles metrics={metrics.data} />
        ) : (
          <EmptyState title="No metrics reported" />
        )}
      </Card>

      <section className="card" aria-labelledby="users-title">
        <header className="card__header">
          <div>
            <h2 className="card__title" id="users-title">
              Users
            </h2>
            <p className="card__desc">
              {users.data ? `${formatNumber(users.data.length)} registered` : 'All accounts'}
            </p>
          </div>
        </header>
        <div className="card__body card__body--flush">
          {users.loading && users.initial ? (
            <SkeletonRows rows={4} />
          ) : users.error ? (
            <ErrorState title="Could not load users" message={users.error} onRetry={users.reload} />
          ) : !users.data || users.data.length === 0 ? (
            <EmptyState title="No users" body="No accounts have been created yet." />
          ) : (
            <TableWrap label="Users">
              <DataTable
                head={
                  <>
                    <Th>Email</Th>
                    <Th>Role</Th>
                    <Th>User ID</Th>
                    <Th>Registered</Th>
                  </>
                }
              >
                {users.data.map((user: User) => (
                  <tr key={user.id}>
                    <Td wrap>{user.email}</Td>
                    <Td>
                      <RolePill role={user.role} />
                    </Td>
                    <Td>
                      <span className="mono" title={user.id}>
                        {shortId(user.id, 12)}
                      </span>
                    </Td>
                    <Td>
                      <span title={formatDateTime(user.created_at)}>
                        {formatRelative(user.created_at)}
                      </span>
                    </Td>
                  </tr>
                ))}
              </DataTable>
            </TableWrap>
          )}
        </div>
      </section>

      <section className="card" aria-labelledby="all-jobs-title">
        <header className="card__header">
          <div>
            <h2 className="card__title" id="all-jobs-title">
              All jobs
            </h2>
            <p className="card__desc">
              {jobItems.length > 0 ? `${formatNumber(jobItems.length)} shown` : 'Across all users'}
            </p>
          </div>
        </header>
        <div className="card__body card__body--flush">
          {jobs.loading && jobs.initial ? (
            <SkeletonRows rows={5} />
          ) : jobs.error ? (
            <ErrorState title="Could not load jobs" message={jobs.error} onRetry={jobs.reload} />
          ) : jobItems.length === 0 ? (
            <EmptyState title="No jobs" body="Nothing has been uploaded yet." />
          ) : (
            <TableWrap label="All jobs">
              <DataTable
                head={
                  <>
                    <Th>File</Th>
                    <Th>Owner</Th>
                    <Th>Status</Th>
                    <Th numeric>Rows</Th>
                    <Th numeric>Valid / Invalid / Dup</Th>
                    <Th numeric>Duration</Th>
                    <Th>Created</Th>
                  </>
                }
              >
                {jobItems.map((job) => (
                  <tr key={job.id}>
                    <Td wrap>
                      <Link to={`/jobs/${job.id}`}>{job.original_filename}</Link>
                      <div className="faint mono">{shortId(job.id, 12)}</div>
                    </Td>
                    <Td wrap>{job.user_email ?? shortId(job.user_id, 12)}</Td>
                    <Td>
                      <StatusPill status={job.status} />
                    </Td>
                    <Td numeric>{formatNumber(job.total_rows)}</Td>
                    <Td numeric>
                      {formatNumber(job.valid_rows)} / {formatNumber(job.invalid_rows)} /{' '}
                      {formatNumber(job.duplicate_rows)}
                    </Td>
                    <Td numeric>{formatDuration(job.duration_ms)}</Td>
                    <Td>
                      <span title={formatDateTime(job.created_at)}>
                        {formatRelative(job.created_at)}
                      </span>
                    </Td>
                  </tr>
                ))}
              </DataTable>
            </TableWrap>
          )}
        </div>
      </section>
    </div>
  )
}

function MetricsTiles({ metrics }: { metrics: SystemMetricsOut }) {
  const failurePct = metrics.job_failure_rate <= 1 ? metrics.job_failure_rate * 100 : metrics.job_failure_rate

  return (
    <div className="stack">
      <div className="grid grid--tiles">
        <StatTile label="Jobs total" value={formatNumber(metrics.jobs_total)} />
        <StatTile
          label="Failure rate"
          value={formatPercent(failurePct)}
          tone={failurePct > 10 ? 'danger' : 'success'}
          hint={`${formatNumber(metrics.jobs_by_status?.failed ?? 0)} failed jobs`}
        />
        <StatTile
          label="Rows processed"
          value={formatNumber(metrics.rows_processed_total)}
          hint={
            metrics.rows_by_status
              ? `${formatNumber(metrics.rows_by_status.valid ?? 0)} valid · ${formatNumber(
                  metrics.rows_by_status.invalid ?? 0,
                )} invalid`
              : undefined
          }
        />
        <StatTile
          label="Avg row time"
          value={`${metrics.avg_row_processing_ms.toFixed(2)} ms`}
          compact
        />
        <StatTile
          label="Avg job duration"
          value={formatDuration(metrics.avg_job_duration_ms)}
          compact
        />
        <StatTile label="Uptime" value={formatUptime(metrics.uptime_seconds)} compact />
      </div>

      <div>
        <p className="stat__label section-label">
          Jobs by status
        </p>
        <ul className="chip-list">
          {STATUS_ORDER.map((status) => (
            <li key={status}>
              <span className="chip chip--neutral">
                {jobStatusLabel(status)}: {formatNumber(metrics.jobs_by_status?.[status] ?? 0)}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

/** `/api/admin/jobs` may answer with a bare list or the standard envelope. */
function normaliseJobs(data: JobList | Job[] | null): Job[] {
  if (!data) return []
  return Array.isArray(data) ? data : data.items
}
