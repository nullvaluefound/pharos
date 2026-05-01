import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: (error: Error, reset: () => void) => ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Catches render-time errors anywhere below it so a single broken component
 * doesn't unmount the whole app and leave the user staring at a blank page.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  reset = () => this.setState({ error: null });

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    if (this.props.fallback) return this.props.fallback(error, this.reset);

    return (
      <div className="m-6 rounded-xl border border-danger-200 bg-danger-50 p-5 text-sm text-danger-800">
        <div className="text-base font-semibold text-danger-900">
          Something broke while rendering this view.
        </div>
        <div className="mt-1 text-danger-700">{error.message}</div>
        {error.stack && (
          <pre className="mt-3 max-h-64 overflow-auto rounded bg-white/60 p-2 text-[11px] text-ink-700">
            {error.stack}
          </pre>
        )}
        <button onClick={this.reset} className="btn-secondary mt-3">
          Try again
        </button>
      </div>
    );
  }
}
