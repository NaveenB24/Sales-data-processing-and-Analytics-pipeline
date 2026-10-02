/**
 * Typed fetch wrapper around the Sales Data Processing API (SPEC §4).
 *
 * - Base URL is '' so every call is same-origin; the Vite dev proxy forwards
 *   `/api` and `/ws` to the backend.
 * - The bearer token is kept in localStorage and injected on every request.
 * - `{detail: "..."}` error bodies are turned into a thrown `ApiError`.
 * - A 401 on any authenticated call clears the session and notifies listeners.
 */

import type {
  ExportFormat,
  HealthOut,
  Job,
  JobList,
  JobRegionReport,
  JobStatusFilter,
  OverviewOut,
  ProgressOut,
  ReportOut,
  RowStatusFilter,
  SystemMetricsOut,
  TokenResponse,
  TransactionList,
  User,
} from './types'

export const API_BASE = ''

const TOKEN_KEY = 'sdp.auth.token'

/* ------------------------------------------------------------------ errors */

export class ApiError extends Error {
  readonly status: number
  readonly detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }

  /** True when the failure is a transport problem rather than an HTTP status. */
  get isNetwork(): boolean {
    return this.status === 0
  }
}

export function errorMessage(error: unknown, fallback = 'Something went wrong.'): string {
  if (error instanceof ApiError) return error.detail
  if (error instanceof Error && error.message) return error.message
  return fallback
}

/* ------------------------------------------------------------ token store */

let memoryToken: string | null = null

export function getToken(): string | null {
  if (memoryToken !== null) return memoryToken
  try {
    memoryToken = window.localStorage.getItem(TOKEN_KEY)
  } catch {
    memoryToken = null
  }
  return memoryToken
}

export function setToken(token: string | null): void {
  memoryToken = token
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token)
    else window.localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* storage disabled (private mode) — the in-memory copy still works */
  }
}

type UnauthorizedHandler = () => void

const unauthorizedHandlers = new Set<UnauthorizedHandler>()

/** Registers an auto-logout listener; returns an unsubscribe function. */
export function onUnauthorized(handler: UnauthorizedHandler): () => void {
  unauthorizedHandlers.add(handler)
  return () => {
    unauthorizedHandlers.delete(handler)
  }
}

function handleUnauthorized(): void {
  setToken(null)
  for (const handler of unauthorizedHandlers) handler()
}

/* ----------------------------------------------------------------- request */

interface RequestOptions {
  method?: string
  /** JSON body — mutually exclusive with `form`. */
  body?: unknown
  /** Multipart body. */
  form?: FormData
  query?: Record<string, string | number | boolean | null | undefined>
  signal?: AbortSignal
  /** Skip the Authorization header (login / signup / health). */
  anonymous?: boolean
}

export function buildUrl(
  path: string,
  query?: RequestOptions['query'],
): string {
  if (!query) return `${API_BASE}${path}`
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined || value === '') continue
    params.set(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${API_BASE}${path}?${qs}` : `${API_BASE}${path}`
}

async function rawRequest(path: string, options: RequestOptions): Promise<Response> {
  const { method = 'GET', body, form, query, signal, anonymous } = options

  const headers: Record<string, string> = { Accept: 'application/json' }
  if (!anonymous) {
    const token = getToken()
    if (token) headers.Authorization = `Bearer ${token}`
  }
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  let response: Response
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers,
      signal,
      body: form ?? (body === undefined ? undefined : JSON.stringify(body)),
    })
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause
    throw new ApiError(0, 'Cannot reach the API. Check that the server is running.')
  }

  if (response.ok) return response

  if (response.status === 401 && !anonymous) handleUnauthorized()

  throw new ApiError(response.status, await readDetail(response))
}

async function readDetail(response: Response): Promise<string> {
  const fallback = `Request failed with status ${response.status}.`
  try {
    const text = await response.text()
    if (!text) return fallback
    const parsed: unknown = JSON.parse(text)
    if (parsed && typeof parsed === 'object' && 'detail' in parsed) {
      const detail = (parsed as { detail: unknown }).detail
      if (typeof detail === 'string') return detail
      // FastAPI validation errors arrive as a list of objects.
      if (Array.isArray(detail)) {
        const messages = detail
          .map((entry) =>
            entry && typeof entry === 'object' && 'msg' in entry
              ? String((entry as { msg: unknown }).msg)
              : null,
          )
          .filter((msg): msg is string => Boolean(msg))
        if (messages.length) return messages.join('; ')
      }
    }
    return fallback
  } catch {
    return fallback
  }
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await rawRequest(path, options)
  if (response.status === 204) return undefined as T
  const text = await response.text()
  if (!text) return undefined as T
  return JSON.parse(text) as T
}

/* ------------------------------------------------------------- downloading */

export interface DownloadedFile {
  blob: Blob
  filename: string
}

async function requestBlob(
  path: string,
  options: RequestOptions,
  fallbackName: string,
): Promise<DownloadedFile> {
  const response = await rawRequest(path, options)
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition)
  return {
    blob: await response.blob(),
    filename: match?.[1] ? decodeURIComponent(match[1]) : fallbackName,
  }
}

/** Hands a downloaded blob to the browser as a file save. */
export function saveFile({ blob, filename }: DownloadedFile): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.rel = 'noopener'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  // Give the browser a tick to start the download before revoking.
  window.setTimeout(() => URL.revokeObjectURL(url), 2000)
}

/* --------------------------------------------------------------- endpoints */

export const api = {
  auth: {
    signup: (email: string, password: string) =>
      request<TokenResponse>('/api/auth/signup', {
        method: 'POST',
        body: { email, password },
        anonymous: true,
      }),

    login: (email: string, password: string) =>
      request<TokenResponse>('/api/auth/login', {
        method: 'POST',
        body: { email, password },
        anonymous: true,
      }),

    me: (signal?: AbortSignal) => request<User>('/api/auth/me', { signal }),
  },

  jobs: {
    upload: (file: File, autoProcess: boolean) => {
      const form = new FormData()
      form.append('file', file)
      form.append('auto_process', String(autoProcess))
      return request<Job>('/api/jobs/upload', {
        method: 'POST',
        form,
        query: { auto_process: autoProcess },
      })
    },

    list: (
      params: { limit?: number; offset?: number; status?: JobStatusFilter },
      signal?: AbortSignal,
    ) =>
      request<JobList>('/api/jobs', {
        signal,
        query: {
          limit: params.limit,
          offset: params.offset,
          status: params.status && params.status !== 'all' ? params.status : undefined,
        },
      }),

    get: (id: string, signal?: AbortSignal) => request<Job>(`/api/jobs/${id}`, { signal }),

    process: (id: string) => request<Job>(`/api/jobs/${id}/process`, { method: 'POST' }),

    reaggregate: (id: string) =>
      request<ReportOut>(`/api/jobs/${id}/reaggregate`, { method: 'POST' }),

    remove: (id: string) => request<void>(`/api/jobs/${id}`, { method: 'DELETE' }),

    rows: (
      id: string,
      params: { status?: RowStatusFilter; limit?: number; offset?: number; q?: string },
      signal?: AbortSignal,
    ) =>
      request<TransactionList>(`/api/jobs/${id}/rows`, {
        signal,
        query: {
          status: params.status && params.status !== 'all' ? params.status : undefined,
          limit: params.limit,
          offset: params.offset,
          q: params.q?.trim() || undefined,
        },
      }),

    report: (id: string, signal?: AbortSignal) =>
      request<ReportOut>(`/api/jobs/${id}/report`, { signal }),

    progress: (id: string, signal?: AbortSignal) =>
      request<ProgressOut>(`/api/jobs/${id}/progress`, { signal }),

    export: (id: string, format: ExportFormat, filenameHint: string) =>
      requestBlob(
        `/api/jobs/${id}/export`,
        { query: { format } },
        `${filenameHint}.${format}`,
      ),
  },

  reports: {
    overview: (signal?: AbortSignal) => request<OverviewOut>('/api/reports/overview', { signal }),

    byRegion: (limit = 10, signal?: AbortSignal) =>
      request<JobRegionReport[]>('/api/reports/by-region', { signal, query: { limit } }),
  },

  admin: {
    users: (signal?: AbortSignal) => request<User[]>('/api/admin/users', { signal }),

    jobs: (signal?: AbortSignal) => request<JobList | Job[]>('/api/admin/jobs', { signal }),
  },

  metrics: (signal?: AbortSignal) => request<SystemMetricsOut>('/api/metrics', { signal }),

  health: (signal?: AbortSignal) =>
    request<HealthOut>('/api/health', { signal, anonymous: true }),
}

/** Absolute `ws(s)://` URL for the live progress socket, token included. */
export function jobSocketUrl(jobId: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const token = getToken() ?? ''
  return `${protocol}//${window.location.host}/ws/jobs/${encodeURIComponent(jobId)}?token=${encodeURIComponent(token)}`
}
