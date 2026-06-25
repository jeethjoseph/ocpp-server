"use client";

import React from "react";
import { Button } from "@/components/ui/button";

interface ErrorBoundaryProps {
  children: React.ReactNode;
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

  handleReset = () => {
    this.setState({ hasError: false });
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
            <Button variant="outline" onClick={this.handleReset}>
              Try again
            </Button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
