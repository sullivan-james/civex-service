import { Component, type ErrorInfo, type ReactNode } from 'react'
import { useLocation } from 'react-router'
import { Button } from './ui'

interface BoundaryProps {
  children: ReactNode
  /** Changing this value clears a caught error (e.g. on navigation). */
  resetKey: string
}

interface BoundaryState {
  error: Error | null
}

class Boundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Route render error', error, info.componentStack)
  }

  componentDidUpdate(prev: BoundaryProps) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) {
      this.setState({ error: null })
    }
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    // A failed lazy-chunk import after a deploy is the most common cause
    // here; a reload fetches the fresh asset manifest.
    return (
      <div
        role="alert"
        className="bg-danger-subtle border border-danger-subtle-border rounded-md px-6 py-8 text-center space-y-3"
      >
        <p className="text-sm font-medium text-danger">
          Something went wrong loading this page.
        </p>
        <p className="text-xs text-fg-muted font-mono break-words">
          {error.message}
        </p>
        <Button onClick={() => window.location.reload()}>Reload</Button>
      </div>
    )
  }
}

/** Catches render errors and failed lazy-route loads below it so one broken
 * page doesn't blank the whole app; navigating elsewhere clears the error. */
export function RouteErrorBoundary({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
  return <Boundary resetKey={pathname}>{children}</Boundary>
}
