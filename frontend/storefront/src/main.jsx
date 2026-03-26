import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./storefront.css";

class StorefrontErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error) {
    console.error("Storefront render failed:", error);
  }

  render() {
    if (!this.state.error) {
      return this.props.children;
    }

    return (
      <section className="storefront-empty storefront-empty--compact">
        <p className="storefront-empty__eyebrow">Storefront unavailable</p>
        <h3>The storefront could not finish rendering.</h3>
        <p>{this.state.error?.message || "A client-side error interrupted the storefront."}</p>
        <a className="storefront-button storefront-button--primary" href="/store/">
          Reload storefront
        </a>
      </section>
    );
  }
}

const bootstrapEl = document.getElementById("storefront-bootstrap");
const rootEl = document.getElementById("storefront-root");

if (bootstrapEl && rootEl) {
  const bootstrap = JSON.parse(bootstrapEl.textContent || "{}");
  createRoot(rootEl).render(
    <React.StrictMode>
      <StorefrontErrorBoundary>
        <App bootstrap={bootstrap} />
      </StorefrontErrorBoundary>
    </React.StrictMode>
  );
}
