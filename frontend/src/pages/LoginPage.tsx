import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'

import { errorMessage } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Button } from '../components/Button'
import { InlineAlert } from '../components/EmptyState'

interface LocationState {
  from?: string
}

export default function LoginPage() {
  const { login, user, loading } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const from = (location.state as LocationState | null)?.from ?? '/'

  if (!loading && user) return <Navigate to={from} replace />

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(email.trim().toLowerCase(), password)
      navigate(from, { replace: true })
    } catch (cause) {
      setError(errorMessage(cause, 'Sign in failed. Check your email and password.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth">
      <div className="auth__panel">
        <div className="auth__brand">
          <span className="brand__mark" aria-hidden="true">
            SD
          </span>
          <strong>Sales Data Pipeline</strong>
        </div>

        <main className="auth__card">
          <h1 className="auth__title">Sign in</h1>
          <p className="auth__sub">Access your uploads, processing jobs and analytics.</p>

          <form className="auth__form" onSubmit={onSubmit} noValidate>
            {error ? <InlineAlert>{error}</InlineAlert> : null}

            <div className="field">
              <label className="field__label" htmlFor="login-email">
                Email address
              </label>
              <input
                id="login-email"
                className="input"
                type="email"
                name="email"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@company.com"
              />
            </div>

            <div className="field">
              <label className="field__label" htmlFor="login-password">
                Password
              </label>
              <input
                id="login-password"
                className="input"
                type="password"
                name="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="••••••••"
              />
            </div>

            <Button type="submit" variant="primary" size="lg" block loading={submitting}>
              Sign in
            </Button>
          </form>

          <p className="auth__foot">
            No account yet? <Link to="/signup">Create one</Link>
          </p>
        </main>
      </div>
    </div>
  )
}
