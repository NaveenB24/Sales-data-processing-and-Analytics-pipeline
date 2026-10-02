import type { ReactNode } from 'react'

export interface CardProps {
  title?: ReactNode
  description?: ReactNode
  actions?: ReactNode
  children: ReactNode
  /** Removes body padding — use for tables that run edge to edge. */
  flush?: boolean
  className?: string
  /** Rendered as a <section> with this accessible name when provided. */
  labelledBy?: string
}

export function Card({
  title,
  description,
  actions,
  children,
  flush = false,
  className,
  labelledBy,
}: CardProps) {
  return (
    <section
      className={['card', className].filter(Boolean).join(' ')}
      aria-labelledby={labelledBy}
    >
      {title || actions ? (
        <header className="card__header">
          <div>
            <h2 className="card__title" id={labelledBy}>
              {title}
            </h2>
            {description ? <p className="card__desc">{description}</p> : null}
          </div>
          {actions ? <div className="card__actions">{actions}</div> : null}
        </header>
      ) : null}
      <div className={flush ? 'card__body card__body--flush' : 'card__body'}>{children}</div>
    </section>
  )
}
