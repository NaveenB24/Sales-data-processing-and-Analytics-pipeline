/**
 * Wire types for the Sales Data Processing API (SPEC §4).
 *
 * Every shape here mirrors a server schema one-to-one. Fields the spec marks as
 * nullable are typed `| null`; fields that are only present on some deployments
 * are optional so the client degrades gracefully instead of crashing.
 */

/* ------------------------------------------------------------------- auth */

export type Role = 'user' | 'admin'

export interface User {
  id: string
  email: string
  role: Role
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user: User
}

export interface Credentials {
  email: string
  password: string
}

/* ------------------------------------------------------------------- jobs */

export type JobStatus = 'pending' | 'queued' | 'processing' | 'completed' | 'failed'

export type RowStatus = 'valid' | 'invalid' | 'duplicate'

export interface Job {
  id: string
  original_filename: string
  status: JobStatus
  total_rows: number
  processed_rows: number
  valid_rows: number
  invalid_rows: number
  duplicate_rows: number
  error_message: string | null
  correlation_id: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  avg_row_ms: number | null
  percent: number
  /** Present on servers that record upload size; not part of the minimum contract. */
  size_bytes?: number
  /** Admin listings join the owning user. */
  user_id?: string
  user_email?: string
}

export interface JobList {
  items: Job[]
  total: number
}

export interface ProgressOut {
  job_id?: string
  status: JobStatus
  total_rows: number
  processed_rows: number
  valid_rows: number
  invalid_rows: number
  duplicate_rows: number
  percent: number
  error_message?: string | null
}

/* -------------------------------------------------------------------- rows */

export interface RowError {
  field: string | null
  code: string
  message: string
}

export interface Transaction {
  id: number
  row_number: number
  transaction_id: string | null
  region: string | null
  product_category: string | null
  quantity: number | null
  unit_price: number | null
  discount_percent: number | null
  transaction_date: string | null
  gross_amount: number | null
  discount_amount: number | null
  net_amount: number | null
  status: RowStatus
  errors: RowError[]
}

export interface TransactionList {
  items: Transaction[]
  total: number
}

/* ----------------------------------------------------------------- reports */

export interface BreakdownItem {
  key: string
  revenue: number
  transactions: number
  share_pct: number
}

export interface TrendPoint {
  period: string
  revenue: number
  transactions: number
  change_pct: number | null
}

export interface TopTransaction {
  transaction_id: string | null
  region: string | null
  product_category: string | null
  quantity: number | null
  unit_price: number | null
  discount_percent: number | null
  transaction_date: string | null
  net_amount: number
}

export interface SummaryMetrics {
  transaction_count: number
  total_revenue: number
  gross_revenue: number
  discount_impact: number
  discount_rate_pct: number
  average_order_value: number
  median_transaction_value: number
  std_dev_order_value: number
  coefficient_of_variation: number
  variance_flag: boolean
  min_order_value: number
  max_order_value: number
}

export interface ReportOut {
  job_id: string
  generated_at: string
  summary: SummaryMetrics
  by_region: BreakdownItem[]
  by_category: BreakdownItem[]
  trend_daily: TrendPoint[]
  trend_monthly: TrendPoint[]
  top_transactions: TopTransaction[]
}

export interface JobRegionReport {
  job_id: string
  original_filename: string
  created_at: string
  status: JobStatus
  by_region: BreakdownItem[]
}

export interface OverviewOut {
  jobs_total: number
  completed_jobs: number
  rows_processed: number
  total_revenue: number
  discount_impact: number
  by_region: BreakdownItem[]
  by_category: BreakdownItem[]
}

/* ------------------------------------------------------------------- admin */

export interface SystemMetricsOut {
  jobs_total: number
  jobs_by_status: Record<string, number>
  job_failure_rate: number
  avg_row_processing_ms: number
  avg_job_duration_ms: number
  rows_processed_total: number
  rows_by_status?: Record<string, number>
  uptime_seconds: number
}

export interface HealthOut {
  status: string
  version: string
  db: string
}

/* --------------------------------------------------------------- websocket */

export type WSMessageType = 'progress' | 'status' | 'completed' | 'failed' | 'ping'

export interface WSMessage {
  type: WSMessageType
  payload?: Partial<ProgressOut> & Record<string, unknown>
}

/* -------------------------------------------------------------- client-side */

export type TrendGranularity = 'daily' | 'monthly'

export type RowStatusFilter = RowStatus | 'all'

export type JobStatusFilter = JobStatus | 'all'

export type ExportFormat = 'csv' | 'json'
