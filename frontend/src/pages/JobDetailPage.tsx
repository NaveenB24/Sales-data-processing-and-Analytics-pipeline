import { useCallback, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api, errorMessage, saveFile } from '../api/client'
import type { ExportFormat, Job, ProgressOut, TrendGranularity } from '../api/types'
import { useAsync } from '../hooks/useAsync'
import { useJobProgress } from '../hooks/useJobProgress'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { EmptyState, ErrorState, InlineAlert } from '../components/EmptyState'
import { ProgressBar } from '../components/ProgressBar'
import { RowExplorer } from '../components/RowExplorer'
import { SkeletonRows } from '../components/Spinner'
import { StatTile } from '../components/StatTile'
import { StatusPill } from '../components/StatusPill'
import { DataTable, TableWrap, Td, Th } from '../components/Table'
import { useToast } from '../components/Toast'
import {
  RevenueByCategoryChart,
  RevenueByRegionChart,
  RevenueTrendChart,
} from '../components/charts'
import {
  ArrowLeftIcon,
  ChartIcon,
  DownloadIcon,
  PlayIcon,
  RefreshIcon,
} from '../components/icons'
import {
  formatCurrency,
  formatDateTime,
  formatDuration,
  formatNumber,
  formatPercent,
} from '../lib/format'

const LIVE_STATUSES = new Set(['queued', 'processing'])

export default function JobDetailPage() {
  const params = useParams<{ jobId: string }>()
  const jobId = params.jobId ?? ''
  const toast = useToast()

  const [granularity, setGranularity] = useState<TrendGranularity>('daily')
  const [exporting, setExporting] = useState<ExportFormat | null>(null)
  const [reaggregating, setReaggregating] = useState(false)
  const [processing, setProcessing] = useState(false)

  const job = useAsync((signal) => api.jobs.get(jobId, signal), [jobId], {
    enabled: Boolean(jobId),
  })

  const isLive = LIVE_STATUSES.has(job.data?.status ?? '')
  const isCompleted = job.data?.status === 'completed'

  const report = useAsync((signal) => api.jobs.report(jobId, signal), [jobId, isCompleted], {
    enabled: Boolean(jobId) && isCompleted,
  })

  const onTerminal = useCallback(
    (progress: ProgressOut) => {
      job.reload()
      report.reload()
      if (progress.status === 'completed') {
        toast.success('Processing finished', `${formatNumber(progress.valid_rows)} valid rows`)
      } else {
        toast.error('Processing failed', progress.error_message ?? 'See the job header for details.')
      }
    },
    [job, report, toast],
  )

  const { progress, transport, connected } = useJobProgress(jobId || null, {
    enabled: isLive,
    onTerminal,
  })

  const current: Job | null = job.data
    ? { ...job.data, ...(progress ? liveOverlay(progress) : {}) }
    : null

  const runProcessing = async () => {
    setProcessing(true)
    try {
      await api.jobs.process(jobId)
      toast.success('Processing queued')
      job.reload()
    } catch (cause) {
      toast.error('Could not start processing', errorMessage(cause))
    } finally {
      setProcessing(false)
    }
  }

  const runReaggregate = async () => {
    setReaggregating(true)
    try {
      const fresh = await api.jobs.reaggregate(jobId)
      report.setData(fresh)
      toast.success('Reports recomputed from stored rows')
    } catch (cause) {
      toast.error('Could not recompute the reports', errorMessage(cause))
    } finally {
      setReaggregating(false)
    }
  }

  const runExport = async (format: ExportFormat) => {
    setExporting(format)
    try {
      const hint = (current?.original_filename ?? `job-${jobId}`).replace(/\.[^.]+$/, '')
      saveFile(await api.jobs.export(jobId, format, `${hint}-results`))
      toast.success(`Export ready (${format.toUpperCase()})`)
    } catch (cause) {
      toast.error('Export failed', errorMessage(cause))
    } finally {
      setExporting(null)
    }
  }

  if (job.loading && job.initial) {
    return (
      <div className="stack">
        <BackLink />
        <Card>
          <SkeletonRows rows={5} />
        </Card>
      </div>
    )
  }

  if (job.error || !current) {
    return (
      <div className="stack">
        <BackLink />
        <Card>
          <ErrorState
            title="Job unavailable"
            message={job.error ?? 'This job could not be loaded.'}
            onRetry={job.reload}
          />
        </Card>
      </div>
    )
  }

  const summary = report.data?.summary
  const trend =
    granularity === 'daily' ? report.data?.trend_daily ?? [] : report.data?.trend_monthly ?? []

  return (
    <div className="stack">
      <BackLink />

      <div className="page-head">
        <div className="page-head__title">
          <div className="row">
            <h1>{current.original_filename}</h1>
            <StatusPill status={current.status} />
          </div>
          <dl className="meta-list">
            <div>
              <dt>Correlation ID</dt>
              <dd className="mono">{current.correlation_id}</dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{formatDateTime(current.created_at)}</dd>
            </div>
            <div>
              <dt>Duration</dt>
              <dd>{formatDuration(current.duration_ms)}</dd>
            </div>
            <div>
              <dt>Avg row time</dt>
              <dd>
                {current.avg_row_ms === null || current.avg_row_ms === undefined
                  ? '—'
                  : `${current.avg_row_ms.toFixed(2)} ms`}
              </dd>
            </div>
          </dl>
        </div>

        <div className="card__actions page-head__actions">
          <Button
            onClick={() => void runProcessing()}
            loading={processing}
            disabled={isLive}
            icon={<PlayIcon size={13} />}
          >
            {current.status === 'pending' ? 'Process' : 'Re-process'}
          </Button>
          <Button
            onClick={() => void runReaggregate()}
            loading={reaggregating}
            icon={<RefreshIcon size={14} />}
          >
            Re-run aggregation
          </Button>
          <Button
            onClick={() => void runExport('csv')}
            loading={exporting === 'csv'}
            icon={<DownloadIcon size={14} />}
          >
            Export CSV
          </Button>
          <Button
            onClick={() => void runExport('json')}
            loading={exporting === 'json'}
            icon={<DownloadIcon size={14} />}
          >
            Export JSON
          </Button>
        </div>
      </div>

      {current.status === 'failed' && current.error_message ? (
        <InlineAlert>
          <strong>Processing failed.</strong> {current.error_message}
        </InlineAlert>
      ) : null}

      {isLive ? (
        <Card
          title="Processing"
          description={
            transport === 'ws'
              ? connected
                ? 'Streaming live over WebSocket.'
                : 'Opening the live connection…'
              : 'WebSocket unavailable — polling every 2 seconds.'
          }
          labelledBy="live-progress-title"
        >
          <ProgressBar
            percent={current.percent}
            processed={current.processed_rows}
            total={current.total_rows}
            indeterminate={current.total_rows === 0}
            label={`Processing progress for ${current.original_filename}`}
          />
        </Card>
      ) : null}

      <div className="grid grid--tiles">
        <StatTile label="Total rows" value={formatNumber(current.total_rows)} />
        <StatTile label="Valid rows" value={formatNumber(current.valid_rows)} tone="success" />
        <StatTile label="Invalid rows" value={formatNumber(current.invalid_rows)} tone="danger" />
        <StatTile label="Duplicates" value={formatNumber(current.duplicate_rows)} tone="warn" />
      </div>

      {!isCompleted ? (
        <Card title="Analytics" labelledBy="analytics-pending-title">
          <EmptyState
            title="No report yet"
            icon={<ChartIcon size={18} />}
            body={
              isLive
                ? 'Metrics appear as soon as processing finishes.'
                : 'Process this job to compute revenue metrics, breakdowns and trends.'
            }
            action={
              isLive ? null : (
                <Button size="sm" onClick={() => void runProcessing()} loading={processing}>
                  Process now
                </Button>
              )
            }
          />
        </Card>
      ) : report.loading && report.initial ? (
        <Card title="Analytics">
          <SkeletonRows rows={4} />
        </Card>
      ) : report.error ? (
        <Card title="Analytics">
          <ErrorState
            title="Report unavailable"
            message={report.error}
            onRetry={report.reload}
          />
        </Card>
      ) : summary && report.data ? (
        <>
          <div className="grid grid--tiles">
            <StatTile
              label="Total revenue"
              value={formatCurrency(summary.total_revenue)}
              tone="accent"
              compact
              hint={`Gross ${formatCurrency(summary.gross_revenue)}`}
            />
            <StatTile
              label="Average order value"
              value={formatCurrency(summary.average_order_value)}
              compact
              hint={`${formatNumber(summary.transaction_count)} valid transactions`}
            />
            <StatTile
              label="Median transaction"
              value={formatCurrency(summary.median_transaction_value)}
              compact
              hint={`Range ${formatCurrency(summary.min_order_value)} – ${formatCurrency(
                summary.max_order_value,
              )}`}
            />
            <StatTile
              label="Std. deviation"
              value={formatCurrency(summary.std_dev_order_value)}
              compact
              tone={summary.variance_flag ? 'warn' : 'default'}
              badge={
                summary.variance_flag ? (
                  <span className="pill pill--warn">High variance</span>
                ) : null
              }
              hint={`Coefficient of variation ${summary.coefficient_of_variation.toFixed(2)}`}
            />
            <StatTile
              label="Discount impact"
              value={formatCurrency(summary.discount_impact)}
              compact
              tone="danger"
              hint={`${formatPercent(summary.discount_rate_pct)} of gross revenue`}
            />
          </div>

          {summary.variance_flag ? (
            <InlineAlert tone="warn">
              <strong>High variance detected.</strong> The coefficient of variation is{' '}
              {summary.coefficient_of_variation.toFixed(2)}, so the average order value is a weak
              summary of this job — read the median and the range alongside it.
            </InlineAlert>
          ) : null}

          <div className="grid grid--halves">
            <Card title="Revenue by region" labelledBy="region-chart-title">
              <RevenueByRegionChart data={report.data.by_region} />
            </Card>
            <Card title="Revenue by category" labelledBy="category-chart-title">
              <RevenueByCategoryChart data={report.data.by_category} />
            </Card>
          </div>

          <Card
            title="Revenue trend"
            labelledBy="trend-chart-title"
            actions={
              <div className="btn-group" role="group" aria-label="Trend granularity">
                <Button
                  aria-pressed={granularity === 'daily'}
                  onClick={() => setGranularity('daily')}
                >
                  Daily
                </Button>
                <Button
                  aria-pressed={granularity === 'monthly'}
                  onClick={() => setGranularity('monthly')}
                >
                  Monthly
                </Button>
              </div>
            }
          >
            <RevenueTrendChart data={trend} granularity={granularity} />
          </Card>

          <section className="card" aria-labelledby="top-transactions-title">
            <header className="card__header">
              <div>
                <h2 className="card__title" id="top-transactions-title">
                  Top 5 transactions
                </h2>
                <p className="card__desc">Highest net amount among the valid rows.</p>
              </div>
            </header>
            <div className="card__body card__body--flush">
              {report.data.top_transactions.length === 0 ? (
                <EmptyState title="No transactions to rank" body="This job has no valid rows." />
              ) : (
                <TableWrap label="Top transactions">
                  <DataTable
                    head={
                      <>
                        <Th numeric>#</Th>
                        <Th>Transaction</Th>
                        <Th>Region</Th>
                        <Th>Category</Th>
                        <Th numeric>Qty</Th>
                        <Th numeric>Unit price</Th>
                        <Th numeric>Discount</Th>
                        <Th numeric>Net amount</Th>
                      </>
                    }
                  >
                    {report.data.top_transactions.map((item, index) => (
                      <tr key={`${item.transaction_id ?? 'row'}-${index}`}>
                        <Td numeric>{index + 1}</Td>
                        <Td>
                          <span className="mono">{item.transaction_id ?? '—'}</span>
                        </Td>
                        <Td>{item.region ?? '—'}</Td>
                        <Td>{item.product_category ?? '—'}</Td>
                        <Td numeric>{formatNumber(item.quantity)}</Td>
                        <Td numeric>{formatCurrency(item.unit_price)}</Td>
                        <Td numeric>{formatPercent(item.discount_percent)}</Td>
                        <Td numeric>
                          <strong>{formatCurrency(item.net_amount)}</strong>
                        </Td>
                      </tr>
                    ))}
                  </DataTable>
                </TableWrap>
              )}
            </div>
          </section>
        </>
      ) : null}

      {jobId ? <RowExplorer jobId={jobId} /> : null}
    </div>
  )
}

function BackLink() {
  return (
    <Link to="/" className="btn btn--ghost btn--sm self-start">
      <ArrowLeftIcon size={14} />
      All jobs
    </Link>
  )
}

/** Live counters from the socket take precedence over the fetched snapshot. */
function liveOverlay(progress: ProgressOut): Partial<Job> {
  return {
    status: progress.status,
    total_rows: progress.total_rows,
    processed_rows: progress.processed_rows,
    valid_rows: progress.valid_rows,
    invalid_rows: progress.invalid_rows,
    duplicate_rows: progress.duplicate_rows,
    percent: progress.percent,
  }
}
