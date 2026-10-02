import type { ButtonHTMLAttributes, ReactNode, Ref } from 'react'

import { Spinner } from './Spinner'

export type ButtonVariant = 'default' | 'primary' | 'danger' | 'ghost'
export type ButtonSize = 'sm' | 'md' | 'lg'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  block?: boolean
  /** Shows a spinner and blocks interaction without changing the button width much. */
  loading?: boolean
  icon?: ReactNode
  ref?: Ref<HTMLButtonElement>
}

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  default: '',
  primary: 'btn--primary',
  danger: 'btn--danger',
  ghost: 'btn--ghost',
}

const SIZE_CLASS: Record<ButtonSize, string> = {
  sm: 'btn--sm',
  md: '',
  lg: 'btn--lg',
}

export function Button({
  variant = 'default',
  size = 'md',
  block = false,
  loading = false,
  icon,
  ref,
  children,
  className,
  disabled,
  type = 'button',
  ...rest
}: ButtonProps) {
  const classes = ['btn', VARIANT_CLASS[variant], SIZE_CLASS[size], block ? 'btn--block' : '', className]
    .filter(Boolean)
    .join(' ')

  return (
    <button
      ref={ref}
      type={type}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Spinner size={size === 'sm' ? 12 : 14} /> : icon}
      {children}
    </button>
  )
}
