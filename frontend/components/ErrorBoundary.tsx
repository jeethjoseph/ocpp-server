"use client";

import React from "react";
import { Button } from "@/components/ui/button";

interface ErrorBoundaryProps {
  children: React.ReactNode;
  // When this changes (e.g. the route pathname), a tripped boundary auto-resets
  // so navigating away from a broken view recovers without a hard reload.
  resetKey?: string | number;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

// Catches render-time throws in the admin/operator route subtree so a single
// component crash shows a recoverable fallback instead of white-screening the
// whole shell. Class component because React error boundaries require the
// lifecycle methods that hooks can't express.
export default class ErrorBoundary extends React.Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("Render error caught by ErrorBoundary", error, info);
  }

  componentDidUpdate(prevProps: ErrorBoundaryProps) {
    // Auto-clear the error when the reset key changes (navigation) — otherwise a
    // deterministic error would re-throw immediately and "Try again" would loop.
    if (this.state.hasError && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false });
    }
  }

  handleReset = () => {
    this.setState({ hasError: false });
  };

  handleReload = () => {
    if (typeof window !== "undefined") window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex items-center justify-center min-h-[400px]">
          <div className="text-center space-y-4">
            <h2 className="text-2xl font-bold text-gray-900 dark:text-gray-100">
              Something went wrong
            </h2>
            <p className="text-gray-600 dark:text-gray-400 max-w-md">
              This view hit an unexpected error. You can try again, or reload the
              page if the problem persists.
            </p>
            <div className="flex items-center justify-center gap-3">
              <Button variant="outline" onClick={this.handleReset}>
                Try again
              </Button>
              <Button onClick={this.handleReload}>Reload page</Button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
