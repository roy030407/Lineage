// Top bar: replay speed controls, wired to POST /api/replay/control.

import { useEffect } from "react";

import type { Role } from "../state/types";
import { useLineageStore } from "../state/store";

const SPEEDS = [1, 10, 60] as const;
const ROLES: { value: Role; label: string }[] = [
  { value: "mirror", label: "Mirror" },
  { value: "operator", label: "Operator" },
  { value: "floor_supervisor", label: "Floor Supervisor" },
  { value: "plant_manager", label: "Plant Manager" },
  { value: "leadership", label: "Leadership" },
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

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  const isPaused = lineState?.playback_mode === "paused";

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "1rem",
        padding: "0.75rem 1rem",
        background: "var(--color-cast-steel)",
        borderBottom: "1px solid var(--color-steel-neutral)",
      }}
    >
      <span style={{ font: "var(--text-h1)" }}>{lineSpec?.plant_name ?? "Lineage"}</span>

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
          defaultValue=""
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

      <button onClick={() => void play()} disabled={!isPaused} aria-pressed={!isPaused}>
        Play
      </button>
      <button onClick={() => void pause()} disabled={isPaused} aria-pressed={isPaused}>
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

      {lineState && (
        <span className="data" style={{ marginLeft: "auto" }}>
          {new Date(lineState.timestamp).toLocaleString()}
        </span>
      )}
    </div>
  );
}
