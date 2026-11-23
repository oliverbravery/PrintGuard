import { Component, StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { markLastInput } from "./a11y";
import { App } from "./App";
import { DrawFailure } from "./components/DrawFailure";
import { captureErrors } from "./log";
import "./styles.css";

class RenderFailure extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? <DrawFailure /> : this.props.children;
  }
}

captureErrors();
markLastInput();
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RenderFailure>
      <App />
    </RenderFailure>
  </StrictMode>,
);
