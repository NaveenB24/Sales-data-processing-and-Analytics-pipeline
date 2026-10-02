import { Component, type ErrorInfo, type ReactNode } from 'react'

import { Button } from './Button'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/**
 * Catches render-time crashes so a single bad component cannot blank the app.
 * Async failures are handled locally by `useAsync`; this is the last resort.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('Unhandled UI error', error, info.componentStack)
  }

  private reset = (): void => {
    this.setState({ error: null })
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <main className="app-main">
        <section className="card">
          <div className="card__body stack">
            <h1>Something broke on this screen</h1>
            <p className="muted">
              The interface hit an unexpected error. Your data is untouched — reloading usually
              clears it.
            </p>
            <pre className="mono muted pre-scroll">
              {error.message}
            </pre>
            <div className="row">
              <Button variant="primary" onClick={this.reset}>
                Try again
              </Button>
              <Button onClick={() => window.location.reload()}>Reload the app</Button>
            </div>
          </div>
        </section>
      </main>
    )
  }
}
