// REST client wrapper for the line/replay/car endpoints. Every path is
// prefixed with VITE_API_BASE_URL when set (a split deployment -- frontend
// on Vercel, backend on Render, different origins). Left unset, it's "",
// so paths stay relative exactly as before: the vite dev server proxies
// /api to the backend locally, no CORS handling needed there either way.
import type {
  AcquisitionMode,
  AuditRecord,
  CarTwin,
  CommissioningBaseline,
  EnvironmentEnvelope,
  FloorSupervisorView,
  LeadershipView,
  LedgerMetrics,
  LineSpec,
  OperatorView,
  PlantManagerView,
  Proposal,
  ReplayControlRequest,
  RunSummary,
  RunToLearnRequest,
  SensorSpec,
  StationSpec,
  TrendState,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function getJson<T>(path: string): Promise<T> {
  const url = `${API_BASE}${path}`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`GET ${url} failed: ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const url = `${API_BASE}${path}`;
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(
      `POST ${url} failed: ${response.status} ${detail?.detail ?? response.statusText}`,
    );
  }
  return (await response.json()) as T;
}

async function putJson<T>(path: string, body: unknown): Promise<T> {
  const url = `${API_BASE}${path}`;
  const response = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(
      `PUT ${url} failed: ${response.status} ${detail?.detail ?? response.statusText}`,
    );
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

export function getOperatorView(stationId: string): Promise<OperatorView> {
  return getJson<OperatorView>(`/api/view/operator?station_id=${encodeURIComponent(stationId)}`);
}

export function getFloorSupervisorView(): Promise<FloorSupervisorView> {
  return getJson<FloorSupervisorView>("/api/view/floor_supervisor");
}

export function getPlantManagerView(): Promise<PlantManagerView> {
  return getJson<PlantManagerView>("/api/view/plant_manager");
}

export function getLeadershipView(): Promise<LeadershipView> {
  return getJson<LeadershipView>("/api/view/leadership");
}

export function startBuilderDraft(): Promise<LineSpec> {
  return postJson<LineSpec>("/api/builder/draft/start");
}

export function getBuilderDraft(): Promise<LineSpec> {
  return getJson<LineSpec>("/api/builder/draft");
}

export function insertBuilderStation(
  station: StationSpec,
  afterStationId: string | null,
): Promise<LineSpec> {
  return postJson<LineSpec>("/api/builder/draft/stations", {
    station,
    after_station_id: afterStationId,
  });
}

export async function removeBuilderStation(stationId: string): Promise<LineSpec> {
  const response = await fetch(
    `${API_BASE}/api/builder/draft/stations/${encodeURIComponent(stationId)}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(`remove station failed: ${response.status} ${detail?.detail ?? ""}`);
  }
  return (await response.json()) as LineSpec;
}

export function moveBuilderStation(
  stationId: string,
  direction: "up" | "down",
): Promise<LineSpec> {
  return postJson<LineSpec>(`/api/builder/draft/stations/${encodeURIComponent(stationId)}/move`, {
    direction,
  });
}

export function saveBuilderDraft(filename: string): Promise<{ ok: boolean; filename: string }> {
  return postJson<{ ok: boolean; filename: string }>("/api/builder/save", { filename });
}

export function activateBuilderDraft(): Promise<LineSpec> {
  return postJson<LineSpec>("/api/builder/activate");
}

export function prependBuilderStation(station: StationSpec): Promise<LineSpec> {
  return postJson<LineSpec>("/api/builder/draft/stations/prepend", { station });
}

export function updateBuilderStationSensors(
  stationId: string,
  sensors: SensorSpec[],
  acquisitionMode: AcquisitionMode,
): Promise<LineSpec> {
  return putJson<LineSpec>(`/api/builder/draft/stations/${encodeURIComponent(stationId)}/sensors`, {
    sensors,
    acquisition_mode: acquisitionMode,
  });
}

export function updateBuilderStationBaseline(
  stationId: string,
  baseline: CommissioningBaseline | null,
): Promise<LineSpec> {
  return putJson<LineSpec>(
    `/api/builder/draft/stations/${encodeURIComponent(stationId)}/commissioning_baseline`,
    { baseline },
  );
}

export function updateBuilderSegmentDistance(
  fromStationId: string,
  toStationId: string,
  distanceM: number,
): Promise<LineSpec> {
  return putJson<LineSpec>("/api/builder/draft/segments/distance", {
    from_station_id: fromStationId,
    to_station_id: toStationId,
    distance_m: distanceM,
  });
}

export function updateBuilderEnvironmentEnvelope(
  envelope: EnvironmentEnvelope,
): Promise<LineSpec> {
  return putJson<LineSpec>("/api/builder/draft/environment_envelope", envelope);
}

export function runToLearn(request: RunToLearnRequest): Promise<CommissioningBaseline> {
  return postJson<CommissioningBaseline>("/api/builder/commissioning/run_to_learn", request);
}

export function assignIssue(
  issueId: string,
  operatorId: string,
): Promise<Record<string, string>> {
  return postJson<Record<string, string>>("/api/floor_supervisor/assignments", {
    issue_id: issueId,
    operator_id: operatorId,
  });
}

export async function unassignIssue(issueId: string): Promise<Record<string, string>> {
  const response = await fetch(
    `${API_BASE}/api/floor_supervisor/assignments/${encodeURIComponent(issueId)}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    throw new Error(`unassign issue failed: ${response.status}`);
  }
  return (await response.json()) as Record<string, string>;
}

export function listActProposals(): Promise<Proposal[]> {
  return getJson<Proposal[]>("/api/act/proposals");
}

export function approveActProposal(proposalId: string, approverId: string): Promise<AuditRecord> {
  return postJson<AuditRecord>(`/api/act/proposals/${encodeURIComponent(proposalId)}/approve`, {
    approver_id: approverId,
  });
}

export function getPredictMetrics(): Promise<LedgerMetrics> {
  return getJson<LedgerMetrics>("/api/predict/metrics");
}

export function getPredictMetricsByStation(): Promise<Record<string, LedgerMetrics>> {
  return getJson<Record<string, LedgerMetrics>>("/api/predict/metrics/by_station");
}

export function getPredictTrend(
  stationId: string,
  interventionAt: string,
  windowSize = 10,
): Promise<TrendState | null> {
  const params = new URLSearchParams({
    intervention_at: interventionAt,
    window_size: String(windowSize),
  });
  return getJson<TrendState | null>(
    `/api/predict/trend/${encodeURIComponent(stationId)}?${params.toString()}`,
  );
}

export async function replayControl(request: ReplayControlRequest): Promise<void> {
  const response = await fetch(`${API_BASE}/api/replay/control`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw new Error(`replay control ${request.action} failed: ${response.status}`);
  }
}
