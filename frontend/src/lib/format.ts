/**
 * Shared formatting helpers. Every money / percent / count that reaches the DOM
 * goes through one of these so the whole app renders numbers identically.
 */

const currency = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const currencyCompact = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  notation: 'compact',
  maximumFractionDigits: 1,
})

const integer = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

const decimal = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const percent = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
})

const dateTime = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
  timeStyle: 'short',
})

const dateOnly = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium' })

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/** `$1,234.50` — the canonical money format (USD, 2dp). */
export function formatCurrency(value: number | null | undefined, fallback = '—'): string {
  return isNum(value) ? currency.format(value) : fallback
}

/** `$1.2K` — for axis ticks and other tight spots. */
export function formatCurrencyCompact(value: number | null | undefined, fallback = '—'): string {
  return isNum(value) ? currencyCompact.format(value) : fallback
}

/** `1,234` */
export function formatNumber(value: number | null | undefined, fallback = '—'): string {
  return isNum(value) ? integer.format(value) : fallback
}

/** `1,234.50` */
export function formatDecimal(value: number | null | undefined, fallback = '—'): string {
  return isNum(value) ? decimal.format(value) : fallback
}

/** `12.5%` — the input is already a percentage (0–100), not a ratio. */
export function formatPercent(value: number | null | undefined, fallback = '—'): string {
  return isNum(value) ? `${percent.format(value)}%` : fallback
}

/** `+12.5%` / `-3.0%` — signed, for period-over-period deltas. */
export function formatDelta(value: number | null | undefined, fallback = '—'): string {
  if (!isNum(value)) return fallback
  const sign = value > 0 ? '+' : ''
  return `${sign}${percent.format(value)}%`
}

/** `1.42 s` / `840 ms` / `2 m 05 s` */
export function formatDuration(ms: number | null | undefined, fallback = '—'): string {
  if (!isNum(ms) || ms < 0) return fallback
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`
  const minutes = Math.floor(ms / 60_000)
  const seconds = Math.round((ms % 60_000) / 1000)
  return `${minutes} m ${String(seconds).padStart(2, '0')} s`
}

/** `3.2 MB` */
export function formatBytes(bytes: number | null | undefined, fallback = '—'): string {
  if (!isNum(bytes) || bytes < 0) return fallback
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unit]}`
}

/** `Oct 2, 2026, 10:32 AM` */
export function formatDateTime(iso: string | null | undefined, fallback = '—'): string {
  const d = toDate(iso)
  return d ? dateTime.format(d) : fallback
}

/** `Oct 2, 2026` */
export function formatDate(iso: string | null | undefined, fallback = '—'): string {
  const d = toDate(iso)
  return d ? dateOnly.format(d) : fallback
}

/** `4 minutes ago` / `in 2 days` */
export function formatRelative(iso: string | null | undefined, fallback = '—'): string {
  const d = toDate(iso)
  if (!d) return fallback
  const diffMs = d.getTime() - Date.now()
  const abs = Math.abs(diffMs)
  const units: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ['second', 1000],
    ['minute', 60_000],
    ['hour', 3_600_000],
    ['day', 86_400_000],
    ['month', 2_592_000_000],
    ['year', 31_536_000_000],
  ]
  let chosen: Intl.RelativeTimeFormatUnit = 'second'
  let size = 1000
  for (const [unit, unitMs] of units) {
    if (abs >= unitMs) {
      chosen = unit
      size = unitMs
    }
  }
  const rtf = new Intl.RelativeTimeFormat('en-US', { numeric: 'auto' })
  return rtf.format(Math.round(diffMs / size), chosen)
}

/** Truncates a long id to `a1b2c3d4…` for dense table cells. */
export function shortId(id: string | null | undefined, length = 8): string {
  if (!id) return '—'
  return id.length <= length ? id : `${id.slice(0, length)}…`
}

/** Human label for an enum-ish wire value: `in_progress` → `In progress`. */
export function titleCase(value: string): string {
  const spaced = value.replace(/[_-]+/g, ' ').trim()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase()
}

/** `30 of 7,412 rows` style range label. */
export function rangeLabel(offset: number, shown: number, total: number, noun = 'rows'): string {
  if (total === 0) return `No ${noun}`
  const from = offset + 1
  const to = offset + shown
  return `${formatNumber(from)}–${formatNumber(to)} of ${formatNumber(total)} ${noun}`
}

function toDate(iso: string | null | undefined): Date | null {
  if (!iso) return null
  // The API emits naive UTC timestamps for some fields; treat those as UTC.
  const normalised = /\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(iso) ? `${iso}Z` : iso
  const d = new Date(normalised)
  return Number.isNaN(d.getTime()) ? null : d
}

/** `3 d 4 h 12 m` — process uptime, which is reported in seconds. */
export function formatUptime(seconds: number | null | undefined, fallback = '—'): string {
  if (!isNum(seconds) || seconds < 0) return fallback
  const days = Math.floor(seconds / 86_400)
  const hours = Math.floor((seconds % 86_400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days > 0) return `${days} d ${hours} h`
  if (hours > 0) return `${hours} h ${minutes} m`
  if (minutes > 0) return `${minutes} m ${Math.floor(seconds % 60)} s`
  return `${Math.floor(seconds)} s`
}
