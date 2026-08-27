// Environment envelope, editable at canvas level (not per-node) -- it's a
// line-wide property SPC reads to decide ENVIRONMENT_INVALID, not something
// any one station owns.

import { useState } from "react";

import { updateBuilderEnvironmentEnvelope } from "../../state/api";
import type { EnvironmentEnvelope, LineSpec } from "../../state/types";

interface Props {
  envelope: EnvironmentEnvelope;
  onUpdated: (line: LineSpec) => void;
}

export function EnvironmentEnvelopeEditor({ envelope, onUpdated }: Props) {
  const [draft, setDraft] = useState<EnvironmentEnvelope>(envelope);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);

  async function handleSave() {
    setError(null);
    setSaving(true);
    try {
      const line = await updateBuilderEnvironmentEnvelope(draft);
      onUpdated(line);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      style={{
        position: "absolute",
        top: "var(--space-4)",
        left: "var(--space-4)",
        zIndex: 5,
        background: "var(--color-cast-steel)",
        border: "1px solid var(--color-steel-neutral)",
        borderRadius: 4,
        padding: "var(--space-3)",
        color: "var(--color-vellum)",
        minWidth: 220,
      }}
    >
      <button onClick={() => setOpen((o) => !o)} style={{ width: "100%" }}>
        {open ? "Hide" : "Edit"} environment envelope
      </button>
      {open && (
        <div style={{ marginTop: "var(--space-2)", display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
          <label>
            Temp min (C)
            <input
              type="number"
              step="any"
              value={draft.temp_min_c}
              onChange={(e) => setDraft((d) => ({ ...d, temp_min_c: Number(e.target.value) }))}
            />
          </label>
          <label>
            Temp max (C)
            <input
              type="number"
              step="any"
              value={draft.temp_max_c}
              onChange={(e) => setDraft((d) => ({ ...d, temp_max_c: Number(e.target.value) }))}
            />
          </label>
          <label>
            Humidity min (%)
            <input
              type="number"
              step="any"
              min={0}
              max={100}
              value={draft.humidity_min_pct}
              onChange={(e) => setDraft((d) => ({ ...d, humidity_min_pct: Number(e.target.value) }))}
            />
          </label>
          <label>
            Humidity max (%)
            <input
              type="number"
              step="any"
              min={0}
              max={100}
              value={draft.humidity_max_pct}
              onChange={(e) => setDraft((d) => ({ ...d, humidity_max_pct: Number(e.target.value) }))}
            />
          </label>
          {error && <p style={{ color: "var(--color-beacon-red)" }}>{error}</p>}
          <button onClick={() => void handleSave()} disabled={saving}>
            {saving ? "Saving…" : "Save envelope"}
          </button>
        </div>
      )}
    </div>
  );
}
