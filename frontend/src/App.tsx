import { Suspense, lazy, type ReactElement } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { useAuth } from './auth/AuthContext'
import { Card } from './components/Card'
import { Layout } from './components/Layout'
import { LoadingBlock } from './components/Spinner'
import DashboardPage from './pages/DashboardPage'
import LoginPage from './pages/LoginPage'
import NotFoundPage from './pages/NotFoundPage'
import SignupPage from './pages/SignupPage'

// Recharts and the admin tables are heavy and not needed on first paint.
const JobDetailPage = lazy(() => import('./pages/JobDetailPage'))
const AdminPage = lazy(() => import('./pages/AdminPage'))

interface ProtectedProps {
  children: ReactElement
  /** Gate the route behind the `admin` role. */
  adminOnly?: boolean
}

function Protected({ children, adminOnly = false }: ProtectedProps) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div className="app">
        <main className="app-main">
          <LoadingBlock label="Restoring your session…" />
        </main>
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }

  if (adminOnly && user.role !== 'admin') {
    return (
      <Layout>
        <Card title="Administrator access required">
          <p className="muted">
            This area is limited to accounts with the <strong>admin</strong> role. Your account is
            signed in as <strong>{user.email}</strong> with the <strong>{user.role}</strong> role.
          </p>
        </Card>
      </Layout>
    )
  }

  return <Layout>{children}</Layout>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />

      <Route
        path="/"
        element={
          <Protected>
            <DashboardPage />
          </Protected>
        }
      />

      <Route
        path="/jobs/:jobId"
        element={
          <Protected>
            <Suspense fallback={<LoadingBlock label="Loading job…" />}>
              <JobDetailPage />
            </Suspense>
          </Protected>
        }
      />

      <Route
        path="/admin"
        element={
          <Protected adminOnly>
            <Suspense fallback={<LoadingBlock label="Loading administration…" />}>
              <AdminPage />
            </Suspense>
          </Protected>
        }
      />

      <Route
        path="*"
        element={
          <Layout>
            <NotFoundPage />
          </Layout>
        }
      />
    </Routes>
  )
}
