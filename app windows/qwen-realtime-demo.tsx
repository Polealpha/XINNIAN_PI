import React from "react";
import ReactDOM from "react-dom/client";

import { ErrorBoundary } from "./components/ErrorBoundary";
import { QwenRealtimeDemoApp } from "./components/QwenRealtimeDemoApp";
import "./ios-theme.css";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Could not find root element to mount to");
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QwenRealtimeDemoApp />
    </ErrorBoundary>
  </React.StrictMode>
);
