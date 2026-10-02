/**
 * Toast notifications. The region is an `aria-live` polite log so screen
 * readers announce results of background actions (upload, delete, export).
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'

import { CloseIcon } from './icons'

export type ToastTone = 'success' | 'error' | 'info'

export interface Toast {
  id: number
  tone: ToastTone
  title: string
  message?: string
}

export interface ToastApi {
  push: (toast: Omit<Toast, 'id'>) => void
  success: (title: string, message?: string) => void
  error: (title: string, message?: string) => void
  info: (title: string, message?: string) => void
  dismiss: (id: number) => void
}

const ToastContext = createContext<ToastApi | null>(null)

const TITLE: Record<ToastTone, string> = {
  success: 'Success',
  error: 'Error',
  info: 'Notice',
}

const DISMISS_AFTER_MS = 6000

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(1)
  const timers = useRef(new Map<number, number>())

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
    const timer = timers.current.get(id)
    if (timer !== undefined) {
      window.clearTimeout(timer)
      timers.current.delete(id)
    }
  }, [])

  const push = useCallback(
    (toast: Omit<Toast, 'id'>) => {
      const id = nextId.current++
      setToasts((current) => [...current.slice(-3), { ...toast, id }])
      timers.current.set(
        id,
        window.setTimeout(() => dismiss(id), DISMISS_AFTER_MS),
      )
    },
    [dismiss],
  )

  useEffect(() => {
    const pending = timers.current
    return () => {
      for (const timer of pending.values()) window.clearTimeout(timer)
      pending.clear()
    }
  }, [])

  const api = useMemo<ToastApi>(
    () => ({
      push,
      dismiss,
      success: (title, message) => push({ tone: 'success', title, message }),
      error: (title, message) => push({ tone: 'error', title, message }),
      info: (title, message) => push({ tone: 'info', title, message }),
    }),
    [push, dismiss],
  )

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toast-region" role="log" aria-live="polite" aria-relevant="additions">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast toast--${toast.tone}`}>
            <span className="toast__accent" aria-hidden="true" />
            <div className="toast__body">
              <p className="toast__title">
                <span className="visually-hidden">{TITLE[toast.tone]}: </span>
                {toast.title}
              </p>
              {toast.message ? <p className="toast__msg">{toast.message}</p> : null}
            </div>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => dismiss(toast.id)}
              aria-label={`Dismiss notification: ${toast.title}`}
            >
              <CloseIcon size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastApi {
  const context = useContext(ToastContext)
  if (!context) throw new Error('useToast must be used inside <ToastProvider>')
  return context
}
