import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { errorMessage } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Button } from '../components/Button'
import { InlineAlert } from '../components/EmptyState'

const MIN_PASSWORD_LENGTH = 8

export default function SignupPage() {
  const { signup, user, loading } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [touched, setTouched] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (!loading && user) return <Navigate to="/" replace />

  const passwordTooShort = password.length > 0 && password.length < MIN_PASSWORD_LENGTH
  const showPasswordError = touched && passwordTooShort

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setTouched(true)
    setError(null)
    if (password.length < MIN_PASSWORD_LENGTH) return

    setSubmitting(true)
    try {
      await signup(email.trim().toLowerCase(), password)
      navigate('/', { replace: true })
    } catch (cause) {
      setError(errorMessage(cause, 'Could not create the account.'))
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
          <h1 className="auth__title">Create an account</h1>
          <p className="auth__sub">Upload transaction files and get analytics in seconds.</p>

          <form className="auth__form" onSubmit={onSubmit} noValidate>
            {error ? <InlineAlert>{error}</InlineAlert> : null}

            <div className="field">
              <label className="field__label" htmlFor="signup-email">
                Email address
              </label>
              <input
                id="signup-email"
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
              <label className="field__label" htmlFor="signup-password">
                Password
              </label>
              <input
                id="signup-password"
                className="input"
                type="password"
                name="password"
                autoComplete="new-password"
                required
                minLength={MIN_PASSWORD_LENGTH}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                onBlur={() => setTouched(true)}
                aria-invalid={showPasswordError || undefined}
                aria-describedby="signup-password-hint"
                placeholder="At least 8 characters"
              />
              {showPasswordError ? (
                <p className="field__error" id="signup-password-hint" role="alert">
                  Password must be at least {MIN_PASSWORD_LENGTH} characters.
                </p>
              ) : (
                <p className="field__hint" id="signup-password-hint">
                  Minimum {MIN_PASSWORD_LENGTH} characters.
                </p>
              )}
            </div>

            <Button
              type="submit"
              variant="primary"
              size="lg"
              block
              loading={submitting}
              disabled={passwordTooShort}
            >
              Create account
            </Button>
          </form>

          <p className="auth__foot">
            Already registered? <Link to="/login">Sign in</Link>
          </p>
        </main>
      </div>
    </div>
  )
}
