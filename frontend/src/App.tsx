// Root component: loads the line spec, connects the live WS stream, and
// renders either the normal top bar + role-view shell, or the Builder
// canvas as its own separate full-screen mode. Builder used to share the
// same header as the role controls (Play/Pause/role-select/Simulate); Phase
// 6 of the gamified rebuild pulled it out into its own entry point instead
// -- BuilderEnterButton below, and BuilderCanvas.tsx's own "Close Builder"
// button to come back, neither of which shares TopBar's control bar.

import { useEffect } from "react";

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

export default function App() {
  const loadLineSpec = useLineageStore((s) => s.loadLineSpec);
  const role = useLineageStore((s) => s.role);
  const builderOpen = useLineageStore((s) => s.builderOpen);

  useEffect(() => {
    void loadLineSpec();
    const disconnect = connectLineWebSocket();
    return disconnect;
  }, [loadLineSpec]);

  if (builderOpen) {
    // No TopBar here at all -- Builder is a wholly separate mode, not a
    // panel swapped in under the same role/replay control bar.
    return <BuilderCanvas />;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <TopBar />
      <div style={{ position: "relative", flex: 1, minHeight: 0, overflowY: "auto" }}>
        {role === "mirror" && (
          <>
            <Scene />
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
