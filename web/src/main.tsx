import { Component, StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { captureErrors } from "./log";
import "./styles.css";

class RenderFailure extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main role="alert" className="grid min-h-dvh place-items-center p-6 text-center">
        <div className="space-y-3">
          <p className="text-text-0">PrintGuard hit an error drawing this page.</p>
          <button className="btn btn-primary" onClick={() => location.reload()}>
            Reload
          </button>
        </div>
      </main>
    );
  }
}

captureErrors();
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RenderFailure>
      <App />
    </RenderFailure>
  </StrictMode>,
);
