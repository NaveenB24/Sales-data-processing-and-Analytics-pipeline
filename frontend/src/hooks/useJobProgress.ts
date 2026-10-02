/**
 * Live job progress.
 *
 * Primary transport is the WebSocket at `/ws/jobs/{id}?token=<jwt>` (SPEC §4).
 * If the socket fails to open within `OPEN_TIMEOUT_MS`, errors, or closes
 * abnormally, the hook falls back to polling `GET /api/jobs/{id}/progress`
 * every `POLL_INTERVAL_MS`. Both transports stop as soon as the job reaches a
 * terminal state, and everything is torn down on unmount.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { api, jobSocketUrl } from '../api/client'
import type { JobStatus, ProgressOut, WSMessage } from '../api/types'

export type ProgressTransport = 'ws' | 'poll'

export interface JobProgressState {
  progress: ProgressOut | null
  /** True while the WebSocket is open, or while polling is succeeding. */
  connected: boolean
  transport: ProgressTransport
}

const OPEN_TIMEOUT_MS = 3000
const POLL_INTERVAL_MS = 2000
const NORMAL_CLOSURE = 1000

const TERMINAL: ReadonlySet<JobStatus> = new Set<JobStatus>(['completed', 'failed'])

export function isTerminal(status: JobStatus | undefined | null): boolean {
  return status ? TERMINAL.has(status) : false
}

export interface UseJobProgressOptions {
  /** Watch only while this is true (e.g. the job is queued or processing). */
  enabled?: boolean
  /** Fired once when the job reaches `completed` or `failed`. */
  onTerminal?: (progress: ProgressOut) => void
}

export function useJobProgress(
  jobId: string | null,
  options: UseJobProgressOptions = {},
): JobProgressState {
  const { enabled = true, onTerminal } = options

  const [progress, setProgress] = useState<ProgressOut | null>(null)
  const [connected, setConnected] = useState(false)
  const [transport, setTransport] = useState<ProgressTransport>('ws')

  const onTerminalRef = useRef<UseJobProgressOptions['onTerminal']>(undefined)
  onTerminalRef.current = onTerminal

  const active = Boolean(jobId) && enabled

  // Guards shared with the effect's listeners; refs so the handlers always read
  // the current value without re-subscribing.
  const firedRef = useRef(false)
  const lastStatusRef = useRef<JobStatus | undefined>(undefined)

  const publish = useCallback((next: ProgressOut) => {
    lastStatusRef.current = next.status
    setProgress(next)
    if (isTerminal(next.status) && !firedRef.current) {
      firedRef.current = true
      onTerminalRef.current?.(next)
    }
  }, [])

  useEffect(() => {
    if (!active || !jobId) {
      setConnected(false)
      return
    }

    firedRef.current = false
    lastStatusRef.current = undefined

    let disposed = false
    let polling = false
    let socket: WebSocket | null = null
    let openTimer: number | undefined
    let pollTimer: number | undefined
    let pollController: AbortController | null = null

    const detachSocket = () => {
      if (!socket) return
      const current = socket
      socket = null
      current.onopen = null
      current.onmessage = null
      current.onerror = null
      current.onclose = null
      if (
        current.readyState === WebSocket.OPEN ||
        current.readyState === WebSocket.CONNECTING
      ) {
        current.close(NORMAL_CLOSURE, 'client closed')
      }
    }

    const teardown = () => {
      disposed = true
      window.clearTimeout(openTimer)
      window.clearTimeout(pollTimer)
      pollController?.abort()
      pollController = null
      detachSocket()
      setConnected(false)
    }

    const pollOnce = async (): Promise<void> => {
      if (disposed) return
      pollController = new AbortController()
      try {
        const next = await api.jobs.progress(jobId, pollController.signal)
        if (disposed) return
        setConnected(true)
        publish(next)
        if (isTerminal(next.status)) {
          teardown()
          return
        }
      } catch (cause) {
        if (disposed) return
        if (cause instanceof DOMException && cause.name === 'AbortError') return
        // Keep retrying: a transient API hiccup should not kill live progress.
        setConnected(false)
      }
      if (!disposed) pollTimer = window.setTimeout(() => void pollOnce(), POLL_INTERVAL_MS)
    }

    const startPolling = () => {
      if (disposed || polling) return
      polling = true
      window.clearTimeout(openTimer)
      detachSocket()
      setTransport('poll')
      void pollOnce()
    }

    try {
      socket = new WebSocket(jobSocketUrl(jobId))
    } catch {
      startPolling()
      return teardown
    }

    // Don't make the user stare at a dead socket: time-box the handshake.
    openTimer = window.setTimeout(() => {
      if (!disposed && socket?.readyState !== WebSocket.OPEN) startPolling()
    }, OPEN_TIMEOUT_MS)

    socket.onopen = () => {
      if (disposed) return
      window.clearTimeout(openTimer)
      setTransport('ws')
      setConnected(true)
    }

    socket.onmessage = (event: MessageEvent<string>) => {
      if (disposed) return
      const next = parseProgressMessage(event.data, jobId)
      if (!next) return
      publish(next)
      if (isTerminal(next.status)) teardown()
    }

    socket.onerror = () => {
      if (!disposed) startPolling()
    }

    socket.onclose = (event: CloseEvent) => {
      if (disposed) return
      setConnected(false)
      // A clean close after a terminal update is the expected ending; any other
      // close means we lost the stream, so keep the UI live by polling.
      const endedCleanly = event.code === NORMAL_CLOSURE && isTerminal(lastStatusRef.current)
      if (endedCleanly) teardown()
      else startPolling()
    }

    return teardown
  }, [active, jobId, publish])

  return { progress, connected, transport }
}

/**
 * Accepts both the enveloped form `{type, payload}` and a flat
 * `{type, ...progress}` message, per SPEC §4.
 */
export function parseProgressMessage(raw: string, jobId: string): ProgressOut | null {
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return null
  }
  if (!parsed || typeof parsed !== 'object') return null

  const message = parsed as WSMessage & Record<string, unknown>
  if (message.type === 'ping') return null

  const source: Record<string, unknown> = {
    ...(message as Record<string, unknown>),
    ...((message.payload ?? {}) as Record<string, unknown>),
  }

  const status = source.status
  if (typeof status !== 'string') return null

  return {
    job_id: typeof source.job_id === 'string' ? source.job_id : jobId,
    status: status as JobStatus,
    total_rows: num(source.total_rows),
    processed_rows: num(source.processed_rows),
    valid_rows: num(source.valid_rows),
    invalid_rows: num(source.invalid_rows),
    duplicate_rows: num(source.duplicate_rows),
    percent: num(source.percent),
    error_message: typeof source.error_message === 'string' ? source.error_message : null,
  }
}

function num(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}
