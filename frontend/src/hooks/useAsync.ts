/**
 * A small request state machine: loading / error / data, plus a `reload`.
 * Every async surface in the app uses it so all four UI states are handled.
 */

import { useCallback, useEffect, useRef, useState, type DependencyList } from 'react'

import { errorMessage } from '../api/client'

export interface AsyncResult<T> {
  data: T | null
  error: string | null
  loading: boolean
  /** True only for the very first load — used to pick skeleton vs. soft refresh. */
  initial: boolean
  reload: () => void
  setData: (updater: T | null | ((previous: T | null) => T | null)) => void
}

export function useAsync<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: DependencyList,
  options: { enabled?: boolean } = {},
): AsyncResult<T> {
  const enabled = options.enabled ?? true
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(enabled)
  const [initial, setInitial] = useState(true)
  const [nonce, setNonce] = useState(0)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      return
    }
    const controller = new AbortController()
    let active = true
    setLoading(true)
    setError(null)

    fetcherRef
      .current(controller.signal)
      .then((result) => {
        if (!active || controller.signal.aborted) return
        setData(result)
        setError(null)
      })
      .catch((cause: unknown) => {
        if (!active || controller.signal.aborted) return
        if (cause instanceof DOMException && cause.name === 'AbortError') return
        setError(errorMessage(cause))
      })
      .finally(() => {
        if (!active || controller.signal.aborted) return
        setLoading(false)
        setInitial(false)
      })

    return () => {
      active = false
      controller.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled, nonce])

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  return { data, error, loading, initial, reload, setData }
}
