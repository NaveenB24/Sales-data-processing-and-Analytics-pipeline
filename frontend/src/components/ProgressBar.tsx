import { formatNumber, formatPercent } from '../lib/format'

export interface ProgressBarProps {
  percent: number
  processed?: number
  total?: number
  /** Short status text shown at the right of the meta row. */
  caption?: string
  tone?: 'default' | 'success' | 'danger'
  /** Compact variant for table rows. */
  inline?: boolean
  /** Renders a moving bar when the total row count is not known yet. */
  indeterminate?: boolean
  label?: string
}

export function ProgressBar({
  percent,
  processed,
  total,
  caption,
  tone = 'default',
  inline = false,
  indeterminate = false,
  label = 'Job progress',
}: ProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, Number.isFinite(percent) ? percent : 0))
  const toneClass =
    tone === 'success' ? 'progress__bar--success' : tone === 'danger' ? 'progress__bar--danger' : ''

  const counter =
    processed !== undefined && total !== undefined
      ? `${formatNumber(processed)} / ${formatNumber(total)} rows`
      : null

  return (
    <div className={inline ? 'progress progress--inline' : 'progress'}>
      <div
        className="progress__track"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={indeterminate ? undefined : Math.round(clamped)}
        aria-valuetext={indeterminate ? 'Starting…' : `${Math.round(clamped)} percent complete`}
      >
        <div
          className={[
            'progress__bar',
            toneClass,
            indeterminate ? 'progress__bar--indeterminate' : '',
          ]
            .filter(Boolean)
            .join(' ')}
          style={{ width: `${clamped}%` }}
        />
      </div>
      {counter || caption ? (
        <p className="progress__meta" aria-live="polite">
          <span>{counter ?? ''}</span>
          <span>{caption ?? formatPercent(clamped)}</span>
        </p>
      ) : null}
    </div>
  )
}
