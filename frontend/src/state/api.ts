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
  ProposalSimulation,
  ReplayControlRequest,
  RunSummary,
  RunToLearnRequest,
  SensorSpec,
  StationSpec,
  TraceResult,
  TrendState,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

// The operator's key, held in sessionStorage rather than compiled in.
// A VITE_ variable would be readable in devtools, which makes it
// obfuscation rather than a credential. Reads and the WebSocket are
// public, so an operator only needs this to control playback, edit a
// line, or approve an Act proposal. The backend gate is inert unless
// LINEAGE_API_KEY is set, so this is normally never needed at all.
const API_KEY_STORAGE = "lineage.apiKey";

export function getApiKey(): string | null {
  try {
    return sessionStorage.getItem(API_KEY_STORAGE);
  } catch {
    // Some privacy modes throw on access rather than returning null.
    return null;
  }
}

export function setApiKey(key: string | null): void {
  try {
    if (key === null) sessionStorage.removeItem(API_KEY_STORAGE);
    else sessionStorage.setItem(API_KEY_STORAGE, key);
  } catch {
    // Nothing useful to do here; the next write is simply rejected
    // and the prompt reappears.
  }
}

function writeHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const key = getApiKey();
  return key === null ? extra : { ...extra, "X-Lineage-Key": key };
}

// A hung request (dropped connection, unresponsive proxy) used to wedge a
// view's loading state forever, with nothing to recover from -- every GET
// now carries a real timeout via AbortController. 30s covers every normal
// endpoint; predict.py's ledger endpoints override it explicitly (see
// getPredictMetrics/getPredictMetricsByStation below) since that build is a
// real, documented ~105s job on first use, not a hang.
const DEFAULT_TIMEOUT_MS = 30_000;

// Some endpoints use HTTP status as real signal (trace's 409 "no run loaded"
// vs 404 "unknown car") -- callers that need to branch on it read .status
// instead of parsing it back out of the message string.
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function getJson<T>(path: string, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  const url = `${API_BASE}${path}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) {
      throw new ApiError(
        `GET ${url} failed: ${response.status} ${response.statusText}`,
        response.status,
      );
    }
    return (await response.json()) as T;
  } finally {
    clearTimeout(timeout);
  }
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const url = `${API_BASE}${path}`;
  const response = await fetch(url, {
    method: "POST",
    headers: writeHeaders({ "Content-Type": "application/json" }),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new ApiError(
      `POST ${url} failed: ${response.status} ${detail?.detail ?? response.statusText}`,
      response.status,
    );
  }
  return (await response.json()) as T;
}

async function putJson<T>(path: string, body: unknown): Promise<T> {
  const url = `${API_BASE}${path}`;
  const response = await fetch(url, {
    method: "PUT",
    headers: writeHeaders({ "Content-Type": "application/json" }),
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
    { method: "DELETE", headers: writeHeaders() },
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
    { method: "DELETE", headers: writeHeaders() },
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

export function simulateActProposal(proposalId: string): Promise<ProposalSimulation> {
  return postJson<ProposalSimulation>(
    `/api/act/proposals/${encodeURIComponent(proposalId)}/simulate`,
  );
}

// 409 when no run is loaded, 404 for a car id unknown to the loaded run --
// both are expected states the CarPanel handles by status, not failures.
export function getCarTrace(carId: string): Promise<TraceResult> {
  return getJson<TraceResult>(`/api/trace/${encodeURIComponent(carId)}`);
}

// The backend's first build assesses every car in the run against every
// inspection station it reached -- ~105s observed for a 400-car run (see
// predict.py's own comment), cached after that. Give it real headroom
// instead of the default 30s timeout.
const PREDICT_LEDGER_TIMEOUT_MS = 120_000;

export function getPredictMetricsByStation(): Promise<Record<string, LedgerMetrics>> {
  return getJson<Record<string, LedgerMetrics>>(
    "/api/predict/metrics/by_station",
    PREDICT_LEDGER_TIMEOUT_MS,
  );
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
    headers: writeHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    // Carries the server's own detail through: a bare status turned
    // "no run loaded" and "missing key" into the same opaque number.
    const detail = await response.json().catch(() => null);
    throw new Error(
      `replay control ${request.action} failed: ${response.status} ${
        detail?.detail ?? response.statusText
      }`,
    );
  }
}

export interface SimulateResult {
  run_id: string;
  num_cars: number;
}

// Generates a fresh 400-car run against the currently loaded line (same
// scenario shape as the committed default run, fresh seed and today's
// start time) and loads it immediately -- confirmed ~11s wall-clock on a
// real 42-station line, so the caller should show real progress, not a
// bare disabled button, for that whole window.
export function simulateRun(): Promise<SimulateResult> {
  return postJson<SimulateResult>("/api/datagen/simulate");
}
