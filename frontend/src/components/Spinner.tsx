export interface SpinnerProps {
  size?: number
  /** Announced to screen readers when the spinner stands alone. */
  label?: string
}

export function Spinner({ size = 16, label }: SpinnerProps) {
  return (
    <>
      <span className="spinner" style={{ width: size, height: size }} aria-hidden="true" />
      {label ? <span className="visually-hidden">{label}</span> : null}
    </>
  )
}

export function LoadingBlock({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="loading-block" role="status">
      <Spinner size={18} />
      <span>{label}</span>
    </div>
  )
}

export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="skeleton-stack" aria-hidden="true">
      {Array.from({ length: rows }, (_, index) => (
        <div
          key={index}
          className="skeleton"
          style={{ height: 14, width: `${100 - index * 9}%` }}
        />
      ))}
    </div>
  )
}
