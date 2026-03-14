/**
 * Error Boundary Component
 *
 * Catches JavaScript errors in child components and displays fallback UI.
 */

import React, { Component, ErrorInfo, ReactNode } from 'react';
import { Alert, Button, Container } from 'react-bootstrap';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
    this.setState({ errorInfo });
  }

  handleReset = (): void => {
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <Container className="mt-5">
          <Alert variant="danger">
            <Alert.Heading>Something went wrong</Alert.Heading>
            <p>
              An unexpected error occurred. Please try refreshing the page.
            </p>
            {process.env.NODE_ENV === 'development' && this.state.error && (
              <pre className="mt-3 p-3 bg-light rounded">
                {this.state.error.toString()}
                {this.state.errorInfo?.componentStack}
              </pre>
            )}
            <hr />
            <Button variant="outline-danger" onClick={this.handleReset}>
              Try Again
            </Button>
          </Alert>
        </Container>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
