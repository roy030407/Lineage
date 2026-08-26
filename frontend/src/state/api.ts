// REST client wrapper for the line/replay/car endpoints. Relative paths only
// -- the vite dev server proxies /api to the backend, no CORS handling needed.

import type { CarTwin, LineSpec, ReplayControlRequest, RunSummary } from "./types";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`GET ${path} failed: ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export function getLine(): Promise<LineSpec> {
  return getJson<LineSpec>("/api/line");
}

export function listRuns(): Promise<RunSummary[]> {
  return getJson<RunSummary[]>("/api/runs");
}

export function getCar(carId: string): Promise<CarTwin> {
  return getJson<CarTwin>(`/api/cars/${encodeURIComponent(carId)}`);
}

export async function replayControl(request: ReplayControlRequest): Promise<void> {
  const response = await fetch("/api/replay/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw new Error(`replay control ${request.action} failed: ${response.status}`);
  }
}
