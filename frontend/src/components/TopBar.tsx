// Top bar: replay speed controls, wired to POST /api/replay/control.

import { useEffect, useState } from "react";

import type { Role } from "../state/types";
import { useLineageStore } from "../state/store";

const SPEEDS = [1, 10, 60] as const;
const STALE_AFTER_MS = 5000;

/** Live-stream health chip: colour + shape + text per the status vocabulary
 * (styles/tokens.ts), never colour alone. Hidden until the first tick ever
 * lands (a connected socket with no run loaded isn't "stale", it's idle). */
function WsStatusChip() {
  const wsConnected = useLineageStore((s) => s.wsConnected);
  const lastTickAt = useLineageStore((s) => s.lastTickAt);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  if (wsConnected && lastTickAt === null) return null;

  let glyph: string;
  let color: string;
  let text: string;
  if (!wsConnected) {
    glyph = "◆";
    color = "var(--color-beacon-red)";
    text = "reconnecting";
  } else {
    const ageMs = now - (lastTickAt ?? now);
    if (ageMs < STALE_AFTER_MS) {
      glyph = "●";
      color = "var(--color-beacon-green)";
      text = "live";
    } else {
      glyph = "▲";
      color = "var(--color-beacon-amber)";
      text = `stale ${Math.floor(ageMs / 1000)}s`;
    }
  }

  return (
    <span
      className="data"
      style={{ display: "inline-flex", alignItems: "center", gap: "var(--space-1)" }}
    >
      <span aria-hidden="true" style={{ color }}>
        {glyph}
      </span>
      <span>{text}</span>
    </span>
  );
}
const ROLES: { value: Role; label: string }[] = [
  { value: "mirror", label: "Mirror" },
  { value: "operator", label: "Operator" },
  { value: "floor_supervisor", label: "Floor Supervisor" },
  { value: "plant_manager", label: "Plant Manager" },
  { value: "leadership", label: "Leadership" },
  { value: "prediction_ledger", label: "Prediction Ledger" },
];

export function TopBar() {
  const lineSpec = useLineageStore((s) => s.lineSpec);
  const lineState = useLineageStore((s) => s.lineState);
  const runs = useLineageStore((s) => s.runs);
  const loadRuns = useLineageStore((s) => s.loadRuns);
  const loadRun = useLineageStore((s) => s.loadRun);
  const play = useLineageStore((s) => s.play);
  const pause = useLineageStore((s) => s.pause);
  const step = useLineageStore((s) => s.step);
  const setSpeed = useLineageStore((s) => s.setSpeed);
  const role = useLineageStore((s) => s.role);
  const setRole = useLineageStore((s) => s.setRole);
  const simulating = useLineageStore((s) => s.simulating);
  const simulateError = useLineageStore((s) => s.simulateError);
  const simulate = useLineageStore((s) => s.simulate);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  const isPaused = lineState?.playback_mode === "paused";
  // With no run loaded there is nothing to play OR pause.
  const nothingLoaded = lineState === null;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--space-4)",
        padding: "var(--space-3) var(--space-4)",
        background: "var(--color-cast-steel)",
        borderBottom: "1px solid var(--color-steel-neutral)",
      }}
    >
      <span style={{ font: "var(--text-h1)" }}>{lineSpec?.plant_name ?? "Lineage"}</span>

      <button
        onClick={() => void simulate()}
        disabled={simulating}
        className={simulating ? "pulse" : undefined}
        style={{
          background: "var(--color-beacon-green)",
          color: "var(--color-foundry)",
          fontWeight: 600,
          border: "none",
        }}
        title="Generate a fresh run and start playing it immediately"
      >
        {simulating ? "Simulating…" : "Simulate"}
      </button>
      {simulateError && (
        <span className="data" style={{ color: "var(--color-beacon-red)" }}>
          {simulateError}
        </span>
      )}

      <select
        value={role}
        onChange={(event) => setRole(event.target.value as Role)}
        aria-label="Select role view"
      >
        {ROLES.map((r) => (
          <option key={r.value} value={r.value}>
            {r.label}
          </option>
        ))}
      </select>

      {runs.length > 0 && (
        <select
          onChange={(event) => void loadRun(event.target.value)}
          // Derived from the WS tick's own run_id, so the selection survives
          // remounts (e.g. closing the Builder) as long as a run is playing.
          value={lineState?.run_id ?? ""}
          aria-label="Select run"
        >
          <option value="" disabled>
            Load a run…
          </option>
          {runs.map((run) => (
            <option key={run.run_id} value={run.run_id}>
              {run.run_id}
            </option>
          ))}
        </select>
      )}

      <button
        onClick={() => void play()}
        disabled={nothingLoaded || !isPaused}
        aria-pressed={!nothingLoaded && !isPaused}
      >
        Play
      </button>
      <button
        onClick={() => void pause()}
        disabled={nothingLoaded || isPaused}
        aria-pressed={!nothingLoaded && isPaused}
      >
        Pause
      </button>
      <button onClick={() => void step()}>Step</button>

      <span className="eyebrow">Speed</span>
      {SPEEDS.map((speed) => (
        <button
          key={speed}
          onClick={() => void setSpeed(speed)}
          aria-pressed={lineState?.speed_multiplier === speed}
        >
          {speed}×
        </button>
      ))}

      <span style={{ marginLeft: "auto", display: "inline-flex", gap: "var(--space-4)" }}>
        <WsStatusChip />
        {lineState && (
          <span className="data">{new Date(lineState.timestamp).toLocaleString()}</span>
        )}
      </span>
    </div>
  );
}
