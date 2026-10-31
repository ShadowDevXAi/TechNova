/**
 * Catch unexpected React render errors so one broken screen does not leave a blank app.
 * API/network errors are handled by the shared API client and screen-level alerts.
 */
import React from "react";

export default class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    console.error("TechNova UI rendering error:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="app-error-boundary">
          <section>
            <span className="app-error-kicker">TECHNOVA PORTAL</span>
            <h1>Something went wrong</h1>
            <p>The page could not be displayed. Reload the portal to try again.</p>
            <button type="button" onClick={() => window.location.reload()}>
              Reload portal
            </button>
          </section>
        </main>
      );
    }

    return this.props.children;
  }
}
