// Operator key entry, surfaced only after a write has actually been
// rejected for want of a key. A deployment that leaves LINEAGE_API_KEY
// unset never shows this at all, because the backend gate is inert there
// and no 401 is ever produced.
//
// The value lives in sessionStorage via state/api.ts, never in the bundle:
// anything compiled in is readable in devtools, which would make it
// obfuscation rather than a credential.

import { useState } from "react";

import { setApiKey } from "../state/api";
import { useLineageStore } from "../state/store";

export function ApiKeyPrompt() {
  const lastError = useLineageStore((s) => s.lastError);
  const clearError = useLineageStore((s) => s.clearError);
  const [value, setValue] = useState("");

  if (lastError === null || !lastError.includes("401")) return null;

  return (
    <div
      role="dialog"
      aria-label="Operator key required"
      className="panel-in"
      style={{
        position: "absolute",
        top: "var(--space-4)",
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 30,
        display: "flex",
        alignItems: "center",
        gap: "var(--space-3)",
        padding: "var(--space-3) var(--space-4)",
        background: "var(--color-hud-panel-deep)",
        border: "var(--border-width-chunky) solid var(--color-hud-accent)",
        borderRadius: "var(--radius-md)",
        boxShadow: "var(--shadow-panel)",
      }}
    >
      <span className="eyebrow">Operator key required</span>
      <input
        type="password"
        aria-label="Operator key"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="X-Lineage-Key"
      />
      <button
        onClick={() => {
          setApiKey(value || null);
          clearError();
        }}
      >
        Save
      </button>
      <button onClick={() => clearError()}>Dismiss</button>
    </div>
  );
}
