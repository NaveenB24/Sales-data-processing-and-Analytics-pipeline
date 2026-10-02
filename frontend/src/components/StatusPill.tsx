import type { JobStatus, RowStatus } from '../api/types'

type Tone = 'neutral' | 'info' | 'success' | 'warn' | 'danger' | 'accent'

const JOB_TONE: Record<JobStatus, Tone> = {
  pending: 'neutral',
  queued: 'info',
  processing: 'accent',
  completed: 'success',
  failed: 'danger',
}

const JOB_LABEL: Record<JobStatus, string> = {
  pending: 'Pending',
  queued: 'Queued',
  processing: 'Processing',
  completed: 'Completed',
  failed: 'Failed',
}

const ROW_TONE: Record<RowStatus, Tone> = {
  valid: 'success',
  invalid: 'danger',
  duplicate: 'warn',
}

const ROW_LABEL: Record<RowStatus, string> = {
  valid: 'Valid',
  invalid: 'Invalid',
  duplicate: 'Duplicate',
}

/** Status is carried by the text as well as the colour, never by colour alone. */
export function StatusPill({ status }: { status: JobStatus }) {
  const live = status === 'processing' || status === 'queued'
  return (
    <span
      className={['pill', `pill--${JOB_TONE[status]}`, live ? 'pill--live' : '']
        .filter(Boolean)
        .join(' ')}
    >
      <span className="pill__dot" />
      {JOB_LABEL[status]}
    </span>
  )
}

export function RowStatusPill({ status }: { status: RowStatus }) {
  return (
    <span className={`pill pill--${ROW_TONE[status]}`}>
      <span className="pill__dot" />
      {ROW_LABEL[status]}
    </span>
  )
}

export function RolePill({ role }: { role: string }) {
  return (
    <span className={`pill ${role === 'admin' ? 'pill--accent' : 'pill--neutral'}`}>
      {role === 'admin' ? 'Admin' : 'User'}
    </span>
  )
}

export const jobStatusLabel = (status: JobStatus): string => JOB_LABEL[status]
