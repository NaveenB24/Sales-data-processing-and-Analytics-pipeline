import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'

import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import type { HealthOut } from '../api/types'
import { Button } from './Button'
import { RolePill } from './StatusPill'
import { MenuIcon } from './icons'

export interface LayoutProps {
  children: React.ReactNode
}

export function Layout({ children }: LayoutProps) {
  const { user, logout } = useAuth()
  const location = useLocation()
  const [navOpen, setNavOpen] = useState(false)
  const [isNarrow, setIsNarrow] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(max-width: 860px)').matches,
  )

  useEffect(() => {
    const query = window.matchMedia('(max-width: 860px)')
    const onChange = (event: MediaQueryListEvent) => setIsNarrow(event.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  // Collapse the mobile nav whenever the route changes.
  useEffect(() => setNavOpen(false), [location.pathname])

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to main content
      </a>

      <header className="app-header">
        <div className="app-header__inner">
          <NavLink to="/" className="brand">
            <span className="brand__mark" aria-hidden="true">
              SD
            </span>
            <span>Sales Pipeline</span>
          </NavLink>

          <Button
            className="nav-toggle"
            variant="ghost"
            size="sm"
            aria-expanded={navOpen}
            aria-controls="primary-nav"
            onClick={() => setNavOpen((open) => !open)}
            icon={<MenuIcon size={18} />}
          >
            <span className="visually-hidden">
              {navOpen ? 'Hide navigation' : 'Show navigation'}
            </span>
          </Button>

          <nav
            className="nav"
            id="primary-nav"
            aria-label="Primary"
            hidden={isNarrow && !navOpen}
          >
            <NavLink to="/" className="nav__link" end>
              Dashboard
            </NavLink>
            {user?.role === 'admin' ? (
              <NavLink to="/admin" className="nav__link">
                Administration
              </NavLink>
            ) : null}
          </nav>

          {user ? (
            <div className="app-header__user">
              <div className="identity">
                <span className="identity__email" title={user.email}>
                  {user.email}
                </span>
                <RolePill role={user.role} />
              </div>
              <Button size="sm" onClick={logout}>
                Sign out
              </Button>
            </div>
          ) : null}
        </div>
      </header>

      <main className="app-main" id="main" tabIndex={-1}>
        {children}
      </main>

      <AppFooter />
    </div>
  )
}

function AppFooter() {
  const [health, setHealth] = useState<HealthOut | null>(null)
  const [reachable, setReachable] = useState<boolean | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    api
      .health(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        setHealth(result)
        setReachable(true)
      })
      .catch(() => {
        if (!controller.signal.aborted) setReachable(false)
      })
    return () => controller.abort()
  }, [])

  return (
    <footer className="app-footer">
      <div className="app-footer__inner">
        <span>Sales Data Processing &amp; Analytics Pipeline</span>
        <span>
          {reachable === null
            ? 'Checking API…'
            : reachable
              ? `API ${health?.status ?? 'ok'} · v${health?.version ?? '—'} · database ${health?.db ?? '—'}`
              : 'API unreachable'}
        </span>
      </div>
    </footer>
  )
}
