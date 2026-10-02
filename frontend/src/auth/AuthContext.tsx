/**
 * Session state: the signed-in user, the bearer token, and the three verbs that
 * change them. The token lives in localStorage so a reload keeps the session;
 * on mount we re-validate it with `GET /api/auth/me`.
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

import { api, getToken, onUnauthorized, setToken } from '../api/client'
import type { User } from '../api/types'

export interface AuthContextValue {
  user: User | null
  token: string | null
  /** True while the stored token is being validated on first paint. */
  loading: boolean
  login: (email: string, password: string) => Promise<User>
  signup: (email: string, password: string) => Promise<User>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => getToken())
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState<boolean>(() => getToken() !== null)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const logout = useCallback(() => {
    setToken(null)
    setTokenState(null)
    setUser(null)
    setLoading(false)
  }, [])

  // Any 401 from anywhere in the app ends the session.
  useEffect(() => onUnauthorized(logout), [logout])

  // Restore the session from the stored token exactly once per token value.
  useEffect(() => {
    if (!token) {
      setUser(null)
      setLoading(false)
      return
    }
    if (user) {
      setLoading(false)
      return
    }
    const controller = new AbortController()
    setLoading(true)
    api.auth
      .me(controller.signal)
      .then((me) => {
        if (!controller.signal.aborted && mounted.current) setUser(me)
      })
      .catch(() => {
        // 401 already triggered logout; anything else means we cannot trust the
        // stored token either, so drop it rather than render a half session.
        if (!controller.signal.aborted && mounted.current) logout()
      })
      .finally(() => {
        if (!controller.signal.aborted && mounted.current) setLoading(false)
      })
    return () => controller.abort()
    // `user` is intentionally excluded: re-running on sign-in would re-fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, logout])

  const adopt = useCallback((accessToken: string, nextUser: User) => {
    setToken(accessToken)
    setTokenState(accessToken)
    setUser(nextUser)
    setLoading(false)
  }, [])

  const login = useCallback(
    async (email: string, password: string) => {
      const result = await api.auth.login(email, password)
      adopt(result.access_token, result.user)
      return result.user
    },
    [adopt],
  )

  const signup = useCallback(
    async (email: string, password: string) => {
      const result = await api.auth.signup(email, password)
      adopt(result.access_token, result.user)
      return result.user
    },
    [adopt],
  )

  const value = useMemo<AuthContextValue>(
    () => ({ user, token, loading, login, signup, logout }),
    [user, token, loading, login, signup, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}
