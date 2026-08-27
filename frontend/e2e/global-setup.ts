// Fails fast with a clear message if the backend isn't up (matches
// scripts/demo.py's own check_prerequisites pattern), then loads and plays
// the default run so every smoke test starts from the same known,
// already-advancing state.

const API_BASE = "http://localhost:8000";
const RUN_ID = "default_400_car_run";

async function control(body: Record<string, unknown>): Promise<void> {
  const response = await fetch(`${API_BASE}/api/replay/control`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`replay control ${JSON.stringify(body)} failed: ${response.status}`);
  }
}

export default async function globalSetup(): Promise<void> {
  try {
    const response = await fetch(`${API_BASE}/api/line`, { signal: AbortSignal.timeout(5000) });
    if (!response.ok) throw new Error(`status ${response.status}`);
  } catch (err) {
    throw new Error(
      `Backend not reachable at ${API_BASE} -- start it first (make dev-backend). ${err}`,
    );
  }

  await control({ action: "load", run_id: RUN_ID });
  await control({ action: "set_speed", speed_multiplier: 60 });
  await control({ action: "play" });
}
