import type { ReactNode } from 'react'

import { AlertIcon, InboxIcon } from './icons'
import { Button } from './Button'

export interface EmptyStateProps {
  title: string
  body?: ReactNode
  action?: ReactNode
  icon?: ReactNode
}

export function EmptyState({ title, body, action, icon }: EmptyStateProps) {
  return (
    <div className="empty">
      <span className="empty__icon">{icon ?? <InboxIcon size={18} />}</span>
      <p className="empty__title">{title}</p>
      {body ? <p className="empty__body">{body}</p> : null}
      {action}
    </div>
  )
}

export interface ErrorStateProps {
  title?: string
  message: string
  onRetry?: () => void
  retryLabel?: string
}

export function ErrorState({
  title = 'Could not load this',
  message,
  onRetry,
  retryLabel = 'Try again',
}: ErrorStateProps) {
  return (
    <div className="empty" role="alert">
      <span className="empty__icon">
        <AlertIcon size={18} />
      </span>
      <p className="empty__title">{title}</p>
      <p className="empty__body">{message}</p>
      {onRetry ? (
        <Button onClick={onRetry} size="sm">
          {retryLabel}
        </Button>
      ) : null}
    </div>
  )
}

export function InlineAlert({
  tone = 'danger',
  children,
}: {
  tone?: 'danger' | 'warn' | 'info'
  children: ReactNode
}) {
  return (
    <div className={`alert alert--${tone}`} role={tone === 'danger' ? 'alert' : 'status'}>
      <AlertIcon size={16} />
      <div className="alert__body">{children}</div>
    </div>
  )
}
