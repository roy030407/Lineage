// Visual editor for LineSpec: add/remove/reorder stations and save the
// result as a new line file. Edits a draft independent of whatever line the
// Mirror is using for replay (see backend api/routes/builder.py) -- opening
// the builder never disturbs a running session.

import { useEffect, useState } from "react";

import {
  getBuilderDraft,
  insertBuilderStation,
  moveBuilderStation,
  removeBuilderStation,
  saveBuilderDraft,
  startBuilderDraft,
} from "../state/api";
import type { LineSpec, StationSpec } from "../state/types";
import { StationBuilderForm } from "./StationBuilderForm";

export function StationBuilder() {
  const [draft, setDraft] = useState<LineSpec | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [insertError, setInsertError] = useState<string | null>(null);
  const [inserting, setInserting] = useState(false);
  const [rowError, setRowError] = useState<string | null>(null);
  const [filename, setFilename] = useState("");
  const [saveResult, setSaveResult] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

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

  async function handleInsert(station: StationSpec, afterStationId: string | null) {
    setInserting(true);
    setInsertError(null);
    try {
      const updated = await insertBuilderStation(station, afterStationId);
      setDraft(updated);
    } catch (err) {
      setInsertError(err instanceof Error ? err.message : String(err));
    } finally {
      setInserting(false);
    }
  }

  async function handleRemove(stationId: string) {
    setRowError(null);
    try {
      const updated = await removeBuilderStation(stationId);
      setDraft(updated);
    } catch (err) {
      setRowError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleMove(stationId: string, direction: "up" | "down") {
    setRowError(null);
    try {
      const updated = await moveBuilderStation(stationId, direction);
      setDraft(updated);
    } catch (err) {
      setRowError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleSave() {
    setSaveError(null);
    setSaveResult(null);
    try {
      const result = await saveBuilderDraft(filename);
      setSaveResult(`Saved as ${result.filename}`);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
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

  return (
    <div
      style={{
        padding: "var(--space-8)",
        color: "var(--color-vellum)",
        display: "flex",
        gap: "var(--space-12)",
      }}
    >
      <div style={{ minWidth: "var(--width-builder-column)" }}>
        <p className="eyebrow">Station Builder — {draft.plant_name}</p>

        {rowError && <p style={{ color: "var(--color-beacon-red)" }}>{rowError}</p>}

        <table className="data" style={{ width: "100%", marginTop: "var(--space-4)" }}>
          <thead>
            <tr>
              <th>#</th>
              <th>Station</th>
              <th>Zone</th>
              <th>Mode</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {draft.stations.map((station, i) => (
              <tr key={station.id}>
                <td>{i}</td>
                <td>
                  {station.name} ({station.id})
                </td>
                <td>{station.zone}</td>
                <td>{station.acquisition_mode}</td>
                <td style={{ display: "flex", gap: "var(--space-1)" }}>
                  <button
                    onClick={() => void handleMove(station.id, "up")}
                    disabled={i <= 1}
                    aria-label={`Move ${station.id} up`}
                  >
                    ↑
                  </button>
                  <button
                    onClick={() => void handleMove(station.id, "down")}
                    disabled={i >= draft.stations.length - 1}
                    aria-label={`Move ${station.id} down`}
                  >
                    ↓
                  </button>
                  <button
                    onClick={() => void handleRemove(station.id)}
                    aria-label={`Remove ${station.id}`}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div style={{ marginTop: "var(--space-6)" }}>
          <p className="eyebrow">Save as new line</p>
          <input
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
            placeholder="my_new_line.yaml"
          />
          <button onClick={() => void handleSave()} style={{ marginLeft: "var(--space-2)" }}>
            Save
          </button>
          {saveResult && <p>{saveResult}</p>}
          {saveError && <p style={{ color: "var(--color-beacon-red)" }}>{saveError}</p>}
        </div>
      </div>

      <div style={{ minWidth: "var(--width-side-panel)" }}>
        <StationBuilderForm
          existingStationIds={draft.stations.map((s) => s.id)}
          onSubmit={(station, after) => void handleInsert(station, after)}
          submitting={inserting}
          error={insertError}
        />
      </div>
    </div>
  );
}
