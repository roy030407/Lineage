// Two commissioning paths, per Task 8: enter known idle/loaded mean+std
// directly, or "run to learn" -- simulate a short idle run then a loaded
// run and capture the resulting distributions. The simulation itself lives
// entirely on the backend (lineage.config.commissioning.run_to_learn): real
// random samples, genuinely computed mean/std, never a fabricated number.
// This wizard only collects the nominal centers a commissioning engineer
// would actually know and displays exactly what came back.

import { useState } from "react";

import { runToLearn, updateBuilderStationBaseline } from "../../state/api";
import type { CommissioningBaseline, ConditionStats, StationSpec } from "../../state/types";
import { stationQuantities } from "./quantities";

interface Props {
  station: StationSpec;
  onClose: () => void;
  onSaved: (line: import("../../state/types").LineSpec) => void;
}

type Mode = "choose" | "manual" | "run_to_learn" | "preview";

function accuracyClassFor(station: StationSpec, quantity: string): string {
  const sensor = station.sensors.find((s) => s.kind === quantity);
  return sensor?.accuracy_class ?? "1.0";
}

function emptyStats(quantities: string[]): ConditionStats {
  return {
    mean: Object.fromEntries(quantities.map((q) => [q, 0])),
    std: Object.fromEntries(quantities.map((q) => [q, 0])),
  };
}

export function CommissioningWizard({ station, onClose, onSaved }: Props) {
  const quantities = stationQuantities(station);
  const [mode, setMode] = useState<Mode>("choose");
  const [idle, setIdle] = useState<ConditionStats>(emptyStats(quantities));
  const [loaded, setLoaded] = useState<ConditionStats>(emptyStats(quantities));
  const [idleNominal, setIdleNominal] = useState<Record<string, number>>(
    Object.fromEntries(quantities.map((q) => [q, 0])),
  );
  const [loadedNominal, setLoadedNominal] = useState<Record<string, number>>(
    Object.fromEntries(quantities.map((q) => [q, 0])),
  );
  const [preview, setPreview] = useState<CommissioningBaseline | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function saveBaseline(baseline: CommissioningBaseline) {
    setBusy(true);
    setError(null);
    try {
      const line = await updateBuilderStationBaseline(station.id, baseline);
      onSaved(line);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleRunToLearn() {
    setBusy(true);
    setError(null);
    try {
      const accuracy_classes = Object.fromEntries(
        quantities.map((q) => [q, accuracyClassFor(station, q)]),
      );
      const baseline = await runToLearn({
        accuracy_classes,
        idle_nominal: idleNominal,
        loaded_nominal: loadedNominal,
      });
      setPreview(baseline);
      setMode("preview");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const overlay = (
    <div
      role="dialog"
      aria-label="Commissioning wizard"
      style={{
        position: "absolute",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 30,
      }}
    >
      <div
        style={{
          background: "var(--color-hud-panel-deep)",
          border: "var(--border-width-chunky) solid var(--color-hud-accent)",
          borderRadius: "var(--radius-chunky)",
          boxShadow: "var(--shadow-panel)",
          padding: "var(--space-6)",
          width: 460,
          maxHeight: "80vh",
          overflowY: "auto",
          color: "var(--color-vellum)",
        }}
      >
        <p className="eyebrow" style={{ margin: 0 }}>
          Commissioning wizard -- {station.id}
        </p>

        {quantities.length === 0 && (
          <p className="data" style={{ color: "var(--color-steel-neutral)" }}>
            This station has no sensors or readable params -- add one first before capturing a
            baseline.
          </p>
        )}

        {quantities.length > 0 && mode === "choose" && (
          <div style={{ display: "flex", gap: "var(--space-2)", marginTop: "var(--space-4)" }}>
            <button onClick={() => setMode("manual")}>Enter known values</button>
            <button onClick={() => setMode("run_to_learn")}>Run to learn</button>
          </div>
        )}

        {mode === "manual" && (
          <>
            {quantities.map((q) => (
              <fieldset key={q} style={{ marginTop: "var(--space-2)", display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
                <legend>{q}</legend>
                <label>
                  Idle mean
                  <input
                    type="number"
                    step="any"
                    value={idle.mean[q]}
                    onChange={(e) =>
                      setIdle((prev) => ({ ...prev, mean: { ...prev.mean, [q]: Number(e.target.value) } }))
                    }
                  />
                </label>
                <label>
                  Idle std
                  <input
                    type="number"
                    step="any"
                    min={0}
                    value={idle.std[q]}
                    onChange={(e) =>
                      setIdle((prev) => ({ ...prev, std: { ...prev.std, [q]: Number(e.target.value) } }))
                    }
                  />
                </label>
                <label>
                  Loaded mean
                  <input
                    type="number"
                    step="any"
                    value={loaded.mean[q]}
                    onChange={(e) =>
                      setLoaded((prev) => ({ ...prev, mean: { ...prev.mean, [q]: Number(e.target.value) } }))
                    }
                  />
                </label>
                <label>
                  Loaded std
                  <input
                    type="number"
                    step="any"
                    min={0}
                    value={loaded.std[q]}
                    onChange={(e) =>
                      setLoaded((prev) => ({ ...prev, std: { ...prev.std, [q]: Number(e.target.value) } }))
                    }
                  />
                </label>
              </fieldset>
            ))}
            <button onClick={() => void saveBaseline({ idle, loaded })} disabled={busy}>
              {busy ? "Saving…" : "Save baseline"}
            </button>
          </>
        )}

        {mode === "run_to_learn" && (
          <>
            <p className="data" style={{ color: "var(--color-steel-neutral)" }}>
              Enter the rough centre you expect for each quantity; a short simulated idle run then
              a loaded run draws real random samples around it (sized by each sensor's own
              accuracy_class) and computes the resulting mean/std.
            </p>
            {quantities.map((q) => (
              <fieldset key={q} style={{ marginTop: "var(--space-2)", display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
                <legend>{q}</legend>
                <label>
                  Idle nominal
                  <input
                    type="number"
                    step="any"
                    value={idleNominal[q]}
                    onChange={(e) =>
                      setIdleNominal((prev) => ({ ...prev, [q]: Number(e.target.value) }))
                    }
                  />
                </label>
                <label>
                  Loaded nominal
                  <input
                    type="number"
                    step="any"
                    value={loadedNominal[q]}
                    onChange={(e) =>
                      setLoadedNominal((prev) => ({ ...prev, [q]: Number(e.target.value) }))
                    }
                  />
                </label>
              </fieldset>
            ))}
            <button onClick={() => void handleRunToLearn()} disabled={busy}>
              {busy ? "Running…" : "Run to learn"}
            </button>
          </>
        )}

        {mode === "preview" && preview && (
          <>
            <p className="eyebrow" style={{ marginTop: "var(--space-2)" }}>
              Captured baseline
            </p>
            {quantities.map((q) => (
              <p key={q} className="data">
                {q}: idle {preview.idle.mean[q]?.toFixed(2)}±{preview.idle.std[q]?.toFixed(2)},
                loaded {preview.loaded.mean[q]?.toFixed(2)}±{preview.loaded.std[q]?.toFixed(2)}
              </p>
            ))}
            <button onClick={() => void saveBaseline(preview)} disabled={busy}>
              {busy ? "Saving…" : "Save this baseline"}
            </button>
          </>
        )}

        {error && <p style={{ color: "var(--color-beacon-red)" }}>{error}</p>}

        <div style={{ marginTop: "var(--space-4)" }}>
          <button onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );

  return overlay;
}
