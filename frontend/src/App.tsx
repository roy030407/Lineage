// Root component: loads the line spec, connects the live WS stream, and
// renders either the normal top bar + role-view shell, or the Builder
// canvas as its own separate full-screen mode. Builder used to share the
// same header as the role controls (Play/Pause/role-select/Simulate); Phase
// 6 of the gamified rebuild pulled it out into its own entry point instead
// -- BuilderEnterButton below, and BuilderCanvas.tsx's own "Close Builder"
// button to come back, neither of which shares TopBar's control bar.

import { useEffect, useState } from "react";

import { ApiKeyPrompt } from "./components/ApiKeyPrompt";
import { BootOverlay } from "./components/BootOverlay";
import { BuilderCanvas } from "./builder/graph/BuilderCanvas";
import { CarPanel } from "./panels/CarPanel";
import { StationPanel } from "./panels/StationPanel";
import { Scene } from "./scene/Scene";
import { TopBar } from "./components/TopBar";
import { connectLineWebSocket } from "./state/wsClient";
import { useLineageStore } from "./state/store";
import { FloorSupervisorView } from "./views/FloorSupervisorView";
import { LeadershipView } from "./views/LeadershipView";
import { OperatorView } from "./views/OperatorView";
import { PlantManagerView } from "./views/PlantManagerView";
import { PredictionLedgerView } from "./views/PredictionLedgerView";

function BuilderEnterButton() {
  const setBuilderOpen = useLineageStore((s) => s.setBuilderOpen);
  return (
    <button
      onClick={() => setBuilderOpen(true)}
      style={{
        position: "absolute",
        bottom: "var(--space-4)",
        left: "var(--space-4)",
        zIndex: 5,
        background: "var(--color-hud-panel-deep)",
        color: "var(--color-vellum)",
        border: "var(--border-width-chunky) solid var(--color-hud-accent)",
        borderRadius: "var(--radius-md)",
        boxShadow: "var(--shadow-panel)",
        padding: "var(--space-2) var(--space-4)",
        fontWeight: 600,
      }}
    >
      Open Builder
    </button>
  );
}

const LINE_SPEC_RETRY_MS = 3000;

/** Shown over the Mirror when the line is loaded but no run is playing --
 * otherwise the canvas is just bare rails with no hint what to do next. */
function NoRunOverlay() {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        pointerEvents: "none",
        zIndex: 4,
      }}
    >
      <p
        style={{
          background: "var(--color-hud-panel-deep)",
          color: "var(--color-vellum)",
          border: "var(--border-width-chunky) solid var(--color-hud-accent)",
          borderRadius: "var(--radius-chunky)",
          boxShadow: "var(--shadow-panel)",
          padding: "var(--space-4) var(--space-6)",
          font: "var(--text-h2)",
        }}
      >
        No run playing. Pick a run from the top bar, or press Simulate
      </p>
    </div>
  );
}

export default function App() {
  const loadLineSpec = useLineageStore((s) => s.loadLineSpec);
  const role = useLineageStore((s) => s.role);
  const builderOpen = useLineageStore((s) => s.builderOpen);
  const lineSpec = useLineageStore((s) => s.lineSpec);
  const lineState = useLineageStore((s) => s.lineState);

  const [lineSpecFailing, setLineSpecFailing] = useState(false);
  const [bannerDismissed, setBannerDismissed] = useState(false);

  useEffect(() => {
    // Uncaught, a single failed line-spec fetch used to leave the Mirror a
    // permanently blank canvas -- retry until it lands, and say so while
    // it's failing.
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    async function attempt() {
      try {
        await loadLineSpec();
        if (!cancelled) setLineSpecFailing(false);
      } catch {
        if (!cancelled) {
          setLineSpecFailing(true);
          retryTimer = setTimeout(() => void attempt(), LINE_SPEC_RETRY_MS);
        }
      }
    }

    void attempt();
    const disconnect = connectLineWebSocket();
    return () => {
      cancelled = true;
      if (retryTimer !== null) clearTimeout(retryTimer);
      disconnect();
    };
  }, [loadLineSpec]);

  if (builderOpen) {
    // No TopBar here at all -- Builder is a wholly separate mode, not a
    // panel swapped in under the same role/replay control bar.
    return <BuilderCanvas />;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {lineSpecFailing && !bannerDismissed && (
        <div
          className="hazard-hatch"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "var(--space-4)",
            padding: "var(--space-2) var(--space-4)",
            color: "var(--color-vellum)",
          }}
        >
          <span>Backend unreachable: could not load the line. Retrying…</span>
          <button onClick={() => setBannerDismissed(true)} aria-label="Dismiss">
            ✕
          </button>
        </div>
      )}
      <TopBar />
      <div style={{ position: "relative", flex: 1, minHeight: 0, overflowY: "auto" }}>
        {role === "mirror" && (
          <>
            <Scene />
            {lineSpec && !lineState && <NoRunOverlay />}
            <StationPanel />
            <CarPanel />
          </>
        )}
        {role === "operator" && <OperatorView />}
        {role === "floor_supervisor" && <FloorSupervisorView />}
        {role === "plant_manager" && <PlantManagerView />}
        {role === "leadership" && <LeadershipView />}
        {role === "prediction_ledger" && <PredictionLedgerView />}
        <BuilderEnterButton />
        <ApiKeyPrompt />
        {/* Last so it paints over everything while the spec loads or
            after it fails. Renders nothing once the spec is ready. */}
        <BootOverlay />
      </div>
    </div>
  );
}
