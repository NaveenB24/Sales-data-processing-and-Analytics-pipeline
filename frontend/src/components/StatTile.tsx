import type { ReactNode } from 'react'

export type StatTone = 'default' | 'accent' | 'success' | 'warn' | 'danger'

export interface StatTileProps {
  label: string
  value: ReactNode
  hint?: ReactNode
  tone?: StatTone
  /** Shrinks the value type for long money figures. */
  compact?: boolean
  badge?: ReactNode
}

const TONE_CLASS: Record<StatTone, string> = {
  default: '',
  accent: 'stat--accent',
  success: 'stat--success',
  warn: 'stat--warn',
  danger: 'stat--danger',
}

export function StatTile({
  label,
  value,
  hint,
  tone = 'default',
  compact = false,
  badge,
}: StatTileProps) {
  return (
    <div className={['stat', TONE_CLASS[tone]].filter(Boolean).join(' ')}>
      <span className="stat__label">{label}</span>
      <span className={compact ? 'stat__value stat__value--sm' : 'stat__value'}>{value}</span>
      {badge}
      {hint ? <span className="stat__hint">{hint}</span> : null}
    </div>
  )
}
