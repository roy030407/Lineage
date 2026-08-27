// The editable Builder mode per DESIGN.md: stations as nodes on a dot-grid
// canvas, zone-coloured headers, typed ports; drag from the tray onto a
// link to insert (splitting that segment), or onto either end to append;
// drag between ports to reorder; click a link to cut it; select a node to
// edit sensors/distance/baseline. Mirror stays view-only -- this is a wholly
// separate canvas, only ever mounted while builderOpen is true.

import type { Connection, Edge, Node, NodeTypes } from "@xyflow/react";
import {
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  activateBuilderDraft,
  getBuilderDraft,
  insertBuilderStation,
  removeBuilderStation,
  saveBuilderDraft,
  startBuilderDraft,
} from "../../state/api";
import { useLineageStore } from "../../state/store";
import type { LineSpec, StationSpec } from "../../state/types";
import { findDropTarget, positionsFor, type DropTarget } from "./canvasLayout";
import { EnvironmentEnvelopeEditor } from "./EnvironmentEnvelopeEditor";
import { PropertiesPanel } from "./PropertiesPanel";
import { STATION_TEMPLATE_MIME, SpawnTray, type StationTemplate } from "./SpawnTray";
import { StationCreateModal } from "./StationCreateModal";
import { StationNode, type StationNodeData } from "./StationNode";

const NODE_TYPES: NodeTypes = { station: StationNode };

function buildNodesAndEdges(line: LineSpec): { nodes: Node<StationNodeData>[]; edges: Edge[] } {
  const positions = positionsFor(line.stations);
  const nodes: Node<StationNodeData>[] = line.stations.map((station, index) => ({
    id: station.id,
    type: "station",
    position: positions.get(station.id) ?? { x: 0, y: 0 },
    data: { station, isFirst: index === 0, isLast: index === line.stations.length - 1 },
    draggable: false,
  }));

  const edges: Edge[] = [];
  for (let i = 0; i < line.stations.length - 1; i++) {
    const from = line.stations[i];
    const to = line.stations[i + 1];
    const segment = line.layout.segments.find(
      (s) => s.from_station_id === from.id && s.to_station_id === to.id,
    );
    edges.push({
      id: `${from.id}->${to.id}`,
      source: from.id,
      target: to.id,
      sourceHandle: "out",
      targetHandle: "in",
      label: segment ? `${segment.distance_m.toFixed(1)}m` : "",
      style: { stroke: "var(--color-steel-neutral)" },
    });
  }
  return { nodes, edges };
}

function BuilderCanvasInner() {
  const [draft, setDraft] = useState<LineSpec | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedStationId, setSelectedStationId] = useState<string | null>(null);
  const [pendingDrop, setPendingDrop] = useState<{ target: DropTarget; template: StationTemplate } | null>(
    null,
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const [filename, setFilename] = useState("");
  const [saveResult, setSaveResult] = useState<string | null>(null);
  const reactFlow = useReactFlow();
  const loadLineSpec = useLineageStore((s) => s.loadLineSpec);
  const setBuilderOpen = useLineageStore((s) => s.setBuilderOpen);

  useEffect(() => {
    let cancelled = false;
    async function init() {
      try {
        const existing = await getBuilderDraft();
        if (!cancelled) setDraft(existing);
      } catch {
        try {
          const started = await startBuilderDraft();
          if (!cancelled) setDraft(started);
        } catch (err) {
          if (!cancelled) setLoadError(err instanceof Error ? err.message : String(err));
        }
      }
    }
    void init();
    return () => {
      cancelled = true;
    };
  }, []);

  const { nodes, edges } = useMemo(
    () => (draft ? buildNodesAndEdges(draft) : { nodes: [], edges: [] }),
    [draft],
  );

  const handleUpdated = useCallback((line: LineSpec) => {
    setDraft(line);
    setActionError(null);
  }, []);

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const raw = event.dataTransfer.getData(STATION_TEMPLATE_MIME);
      if (!raw || !draft) return;
      const template = JSON.parse(raw) as StationTemplate;
      const point = reactFlow.screenToFlowPosition({ x: event.clientX, y: event.clientY });
      const positions = positionsFor(draft.stations);
      const target = findDropTarget(point, draft.stations, positions);
      if (!target) {
        setActionError("Drop onto an existing link, or onto either end of the line, to insert.");
        return;
      }
      setPendingDrop({ target, template });
    },
    [draft, reactFlow],
  );

  const handleConnect = useCallback(
    async (connection: Connection) => {
      if (!draft || !connection.source || !connection.target) return;
      if (connection.source === connection.target) return;
      const moving = draft.stations.find((s) => s.id === connection.target);
      if (!moving) return;
      // Reorders by composing the already-tested remove/insert primitives:
      // drop the target station, then re-insert the exact same StationSpec
      // right after the source station -- the same rejoin/split geometry
      // logic the tray-drop insert path uses either way.
      try {
        await removeBuilderStation(moving.id);
        const updated = await insertBuilderStation(moving, connection.source);
        setDraft(updated);
        setActionError(null);
      } catch (err) {
        setActionError(err instanceof Error ? err.message : String(err));
      }
    },
    [draft],
  );

  const handleCutLink = useCallback(
    async (edge: Edge) => {
      setActionError(null);
      try {
        const updated = await removeBuilderStation(edge.target);
        setDraft(updated);
        if (selectedStationId === edge.target) setSelectedStationId(null);
      } catch (err) {
        setActionError(err instanceof Error ? err.message : String(err));
      }
    },
    [selectedStationId],
  );

  async function handleSave() {
    setSaveResult(null);
    setActionError(null);
    try {
      const result = await saveBuilderDraft(filename);
      const activated = await activateBuilderDraft();
      setDraft(activated);
      await loadLineSpec();
      setSaveResult(`Saved as ${result.filename} and activated -- the Mirror now reflects it.`);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    }
  }

  if (loadError) {
    return (
      <div style={{ padding: "var(--space-8)", color: "var(--color-vellum)" }}>
        <p className="hazard-hatch" style={{ padding: "var(--space-2)" }}>
          Could not start a builder draft: {loadError}
        </p>
      </div>
    );
  }

  if (!draft) {
    return (
      <div style={{ padding: "var(--space-8)", color: "var(--color-vellum)" }}>
        <p className="hazard-hatch" style={{ padding: "var(--space-2)" }}>
          Loading draft…
        </p>
      </div>
    );
  }

  const selectedStation: StationSpec | null =
    draft.stations.find((s) => s.id === selectedStationId) ?? null;

  return (
    <div style={{ position: "relative", height: "100%", width: "100%" }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        onNodeClick={(_, node) => setSelectedStationId(node.id)}
        onPaneClick={() => setSelectedStationId(null)}
        onEdgeClick={(_, edge) => void handleCutLink(edge)}
        onConnect={(connection) => void handleConnect(connection)}
        onDrop={handleDrop}
        onDragOver={(event) => event.preventDefault()}
        fitView
        fitViewOptions={{ minZoom: 0.05 }}
        minZoom={0.05}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={24} color="var(--color-steel-neutral)" />
        <Controls />
      </ReactFlow>

      <EnvironmentEnvelopeEditor envelope={draft.environment_envelope} onUpdated={handleUpdated} />

      <div
        style={{
          position: "absolute",
          top: "var(--space-4)",
          right: "var(--space-4)",
          zIndex: 5,
          background: "var(--color-cast-steel)",
          border: "1px solid var(--color-steel-neutral)",
          borderRadius: 4,
          padding: "var(--space-3)",
          color: "var(--color-vellum)",
          display: selectedStation ? "none" : "flex",
          flexDirection: "column",
          gap: "var(--space-2)",
        }}
      >
        <p className="eyebrow" style={{ margin: 0 }}>
          {draft.plant_name}
        </p>
        <input
          value={filename}
          onChange={(e) => setFilename(e.target.value)}
          placeholder="my_new_line.yaml"
        />
        <button onClick={() => void handleSave()}>Save &amp; activate</button>
        <button onClick={() => setBuilderOpen(false)}>Close Builder</button>
        {saveResult && <p className="data">{saveResult}</p>}
        {actionError && <p style={{ color: "var(--color-beacon-red)" }}>{actionError}</p>}
      </div>

      {selectedStation && (
        <PropertiesPanel
          station={selectedStation}
          line={draft}
          onUpdated={handleUpdated}
          onClose={() => setSelectedStationId(null)}
        />
      )}

      <SpawnTray />

      {pendingDrop && (
        <StationCreateModal
          target={pendingDrop.target}
          template={pendingDrop.template}
          existingStationIds={draft.stations.map((s) => s.id)}
          onCancel={() => setPendingDrop(null)}
          onCreated={(line) => {
            setDraft(line);
            setPendingDrop(null);
          }}
        />
      )}
    </div>
  );
}

export function BuilderCanvas() {
  return (
    <ReactFlowProvider>
      <BuilderCanvasInner />
    </ReactFlowProvider>
  );
}
