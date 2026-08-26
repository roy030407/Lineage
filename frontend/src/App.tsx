// Root component: loads the line spec, connects the live WS stream, and
// renders the top bar + 3D Mirror + whichever side panel is active.

import { useEffect } from "react";

import { StationBuilder } from "./builder/StationBuilder";
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

export default function App() {
  const loadLineSpec = useLineageStore((s) => s.loadLineSpec);
  const role = useLineageStore((s) => s.role);
  const builderOpen = useLineageStore((s) => s.builderOpen);

  useEffect(() => {
    void loadLineSpec();
    const disconnect = connectLineWebSocket();
    return disconnect;
  }, [loadLineSpec]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <TopBar />
      <div style={{ position: "relative", flex: 1, minHeight: 0, overflowY: "auto" }}>
        {builderOpen ? (
          <StationBuilder />
        ) : (
          <>
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
          </>
        )}
      </div>
    </div>
  );
}
