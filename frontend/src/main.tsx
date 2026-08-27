// Entry point: mounts <App /> into the DOM.

import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import { initTestHooks } from "./testHooks";
import { applyDesignTokens } from "./styles/tokens";
import "./styles/tokens.css";

applyDesignTokens();
initTestHooks();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
