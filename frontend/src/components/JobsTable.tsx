/**
 * The jobs list: status filter, pagination, per-row actions, and a live
 * progress strip under any job that is queued or processing.
 */

import { useId, useState } from 'react'
import { Link } from 'react-router-dom'

import { api, errorMessage } from '../api/client'
import type { Job, JobStatusFilter } from '../api/types'
import { useJobProgress } from '../hooks/useJobProgress'
import { formatDateTime, formatNumber, formatRelative, shortId } from '../lib/format'
import { Button } from './Button'
import { ConfirmDialog } from './ConfirmDialog'
import { EmptyState, ErrorState } from './EmptyState'
import { Pagination } from './Pagination'
import { ProgressBar } from './ProgressBar'
import { SkeletonRows } from './Spinner'
import { StatusPill } from './StatusPill'
import { DataTable, TableWrap, Td, Th } from './Table'
import { useToast } from './Toast'
import { FileIcon, PlayIcon, TrashIcon } from './icons'

const STATUS_OPTIONS: Array<{ value: JobStatusFilter; label: string }> = [
  { value: 'all', label: 'All statuses' },
  { value: 'pending', label: 'Pending' },
  { value: 'queued', label: 'Queued' },
  { value: 'processing', label: 'Processing' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
]

const COLUMN_COUNT = 6

export interface JobsTableProps {
  jobs: Job[]
  total: number
  offset: number
  limit: number
  status: JobStatusFilter
  loading: boolean
  initialLoad: boolean
  error: string | null
  onStatusChange: (status: JobStatusFilter) => void
  onOffsetChange: (offset: number) => void
  onRefresh: () => void
}

export function JobsTable({
  jobs,
  total,
  offset,
  limit,
  status,
  loading,
  initialLoad,
  error,
  onStatusChange,
  onOffsetChange,
  onRefresh,
}: JobsTableProps) {
  const toast = useToast()
  const filterId = useId()
  const [pendingAction, setPendingAction] = useState<string | null>(null)
  const [toDelete, setToDelete] = useState<Job | null>(null)
  const [deleting, setDeleting] = useState(false)

  const process = async (job: Job) => {
    setPendingAction(job.id)
    try {
      await api.jobs.process(job.id)
      toast.success('Processing queued', job.original_filename)
      onRefresh()
    } catch (cause) {
      toast.error('Could not start processing', errorMessage(cause))
    } finally {
      setPendingAction(null)
    }
  }

  const confirmDelete = async () => {
    if (!toDelete) return
    setDeleting(true)
    try {
      await api.jobs.remove(toDelete.id)
      toast.success('Job deleted', toDelete.original_filename)
      setToDelete(null)
      onRefresh()
    } catch (cause) {
      toast.error('Could not delete the job', errorMessage(cause))
    } finally {
      setDeleting(false)
    }
  }

  const filter = (
    <div className="toolbar">
      <div className="field">
        <label className="field__label" htmlFor={filterId}>
          Status
        </label>
        <select
          id={filterId}
          className="select"
          value={status}
          onChange={(event) => onStatusChange(event.target.value as JobStatusFilter)}
        >
          {STATUS_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      <Button size="sm" onClick={onRefresh} loading={loading && !initialLoad}>
        Refresh
      </Button>
    </div>
  )

  let body: React.ReactNode

  if (initialLoad && loading) {
    body = <SkeletonRows rows={5} />
  } else if (error) {
    body = <ErrorState title="Could not load jobs" message={error} onRetry={onRefresh} />
  } else if (jobs.length === 0) {
    body = (
      <EmptyState
        title={status === 'all' ? 'No jobs yet' : `No ${status} jobs`}
        body={
          status === 'all'
            ? 'Upload a CSV or JSON file to create your first processing job.'
            : 'Try a different status filter.'
        }
        icon={<FileIcon size={18} />}
        action={
          status === 'all' ? null : (
            <Button size="sm" onClick={() => onStatusChange('all')}>
              Show all jobs
            </Button>
          )
        }
      />
    )
  } else {
    body = (
      <>
        <TableWrap label="Processing jobs">
          <DataTable
            head={
              <>
                <Th>File</Th>
                <Th>Status</Th>
                <Th numeric>Rows</Th>
                <Th numeric>Valid / Invalid / Dup</Th>
                <Th>Created</Th>
                <Th numeric>Actions</Th>
              </>
            }
          >
            {jobs.map((job) => {
              const live = job.status === 'queued' || job.status === 'processing'
              const busy = pendingAction === job.id
              return (
                <JobRows
                  key={job.id}
                  job={job}
                  live={live}
                  busy={busy}
                  onProcess={() => void process(job)}
                  onDelete={() => setToDelete(job)}
                  onFinished={onRefresh}
                />
              )
            })}
          </DataTable>
        </TableWrap>
        <Pagination
          offset={offset}
          limit={limit}
          total={total}
          shown={jobs.length}
          noun="jobs"
          onChange={onOffsetChange}
          disabled={loading}
        />
      </>
    )
  }

  return (
    <section className="card" aria-labelledby="jobs-table-title">
      <header className="card__header">
        <div>
          <h2 className="card__title" id="jobs-table-title">
            Processing jobs
          </h2>
          <p className="card__desc">
            {total > 0 ? `${formatNumber(total)} total` : 'Newest first'}
          </p>
        </div>
        <div className="card__actions">{filter}</div>
      </header>
      <div className="card__body card__body--flush">{body}</div>

      <ConfirmDialog
        open={toDelete !== null}
        title="Delete this job?"
        body={`“${toDelete?.original_filename ?? ''}” and all of its rows and reports will be permanently removed. This cannot be undone.`}
        confirmLabel="Delete job"
        destructive
        busy={deleting}
        onConfirm={() => void confirmDelete()}
        onCancel={() => setToDelete(null)}
      />
    </section>
  )
}

interface JobRowsProps {
  job: Job
  live: boolean
  busy: boolean
  onProcess: () => void
  onDelete: () => void
  onFinished: () => void
}

function JobRows({ job, live, busy, onProcess, onDelete, onFinished }: JobRowsProps) {
  const { progress, transport, connected } = useJobProgress(job.id, {
    enabled: live,
    onTerminal: onFinished,
  })

  const current = progress ?? job
  const canProcess = job.status === 'pending' || job.status === 'failed' || job.status === 'completed'

  return (
    <>
      <tr>
        <Td wrap>
          <Link to={`/jobs/${job.id}`}>{job.original_filename}</Link>
          <div className="faint mono">{shortId(job.id, 12)}</div>
        </Td>
        <Td>
          <StatusPill status={current.status} />
        </Td>
        <Td numeric>{formatNumber(current.total_rows)}</Td>
        <Td numeric>
          <span className="num">
            {formatNumber(current.valid_rows)} / {formatNumber(current.invalid_rows)} /{' '}
            {formatNumber(current.duplicate_rows)}
          </span>
        </Td>
        <Td>
          <span title={formatDateTime(job.created_at)}>{formatRelative(job.created_at)}</span>
        </Td>
        <Td numeric>
          <div className="cell-actions">
            <Link to={`/jobs/${job.id}`} className="btn btn--sm">
              View
            </Link>
            <Button
              size="sm"
              onClick={onProcess}
              loading={busy}
              disabled={!canProcess}
              icon={<PlayIcon size={12} />}
              title={
                canProcess
                  ? 'Queue this job for processing'
                  : 'This job is already queued or running'
              }
            >
              Process
            </Button>
            <Button
              size="sm"
              variant="danger"
              onClick={onDelete}
              icon={<TrashIcon size={12} />}
              aria-label={`Delete ${job.original_filename}`}
            >
              Delete
            </Button>
          </div>
        </Td>
      </tr>

      {live ? (
        <tr>
          <td colSpan={COLUMN_COUNT}>
            <ProgressBar
              inline
              label={`Progress for ${job.original_filename}`}
              percent={current.percent}
              processed={current.processed_rows}
              total={current.total_rows}
              indeterminate={current.total_rows === 0}
              caption={`${Math.round(current.percent)}% · ${
                transport === 'ws'
                  ? connected
                    ? 'live'
                    : 'connecting…'
                  : 'polling every 2 s'
              }`}
            />
          </td>
        </tr>
      ) : null}
    </>
  )
}
