// Root component: loads the line spec, connects the live WS stream, and
// renders the top bar + 3D Mirror + whichever side panel is active.

import { useEffect } from "react";

import { CarPanel } from "./panels/CarPanel";
import { StationPanel } from "./panels/StationPanel";
import { Scene } from "./scene/Scene";
import { TopBar } from "./components/TopBar";
import { connectLineWebSocket } from "./state/wsClient";
import { useLineageStore } from "./state/store";

export default function App() {
  const loadLineSpec = useLineageStore((s) => s.loadLineSpec);

  useEffect(() => {
    void loadLineSpec();
    const disconnect = connectLineWebSocket();
    return disconnect;
  }, [loadLineSpec]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <TopBar />
      <div style={{ position: "relative", flex: 1, minHeight: 0 }}>
        <Scene />
        <StationPanel />
        <CarPanel />
      </div>
    </div>
  );
}
