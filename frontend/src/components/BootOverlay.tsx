// What the Mirror shows before the LineSpec arrives, and what it shows if
// that request fails.
//
// Previously neither state existed. loadLineSpec had no catch, so a failed
// getLine() left lineSpec null forever behind an empty canvas: no message,
// no spinner, no way to retry, and nothing in the UI to distinguish "still
// loading" from "the backend is down".

import { useLineageStore } from "../state/store";

function Sweep() {
  return (
    <div
      aria-hidden
      style={{
        width: "220px",
        height: "3px",
        marginTop: "var(--space-4)",
        background: "var(--color-cast-steel)",
        overflow: "hidden",
        borderRadius: "2px",
      }}
    >
      <div
        className="boot-sweep"
        style={{ height: "100%", width: "40%", background: "var(--color-hud-accent)" }}
      />
    </div>
  );
}

export function BootOverlay() {
  const status = useLineageStore((s) => s.lineSpecStatus);
  const lastError = useLineageStore((s) => s.lastError);
  const retry = useLineageStore((s) => s.retryLoadLineSpec);

  if (status === "ready") return null;

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: "absolute",
        inset: 0,
        zIndex: 20,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--color-foundry)",
        color: "var(--color-vellum)",
        textAlign: "center",
        padding: "var(--space-4)",
      }}
    >
      <span style={{ font: "var(--text-h1)", letterSpacing: "var(--letter-spacing-eyebrow)" }}>
        LINEAGE
      </span>
      {status === "error" ? (
        <>
          <p
            className="eyebrow"
            style={{ color: "var(--color-beacon-red)", marginTop: "var(--space-3)" }}
          >
            Could not reach the line
          </p>
          <p className="data" style={{ maxWidth: "48ch", opacity: 0.85 }}>
            {lastError}
          </p>
          <button style={{ marginTop: "var(--space-3)" }} onClick={() => void retry()}>
            Retry
          </button>
        </>
      ) : (
        <>
          <p className="eyebrow" style={{ marginTop: "var(--space-3)" }}>
            Reading line specification
          </p>
          <Sweep />
        </>
      )}
    </div>
  );
}
