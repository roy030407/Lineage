// TypeScript mirrors of the backend Pydantic models Mirror actually consumes.
// Hand-kept in sync with backend/lineage/config, replay, and twin.

export type Zone = "body" | "paint" | "final";
export type AcquisitionMode = "instrumented" | "manual" | "mixed";
export type SensorKind =
  | "thermal"
  | "infrared"
  | "vibration"
  | "torque"
  | "rpm"
  | "cycle_time"
  | "none";

export interface SensorSpec {
  id: string;
  kind: SensorKind;
  unit: string;
  sample_rate_hz: number;
  install_date: string;
  last_calibration_date: string;
  accuracy_class: string;
}

export interface ConditionStats {
  mean: Record<string, number>;
  std: Record<string, number>;
}

export interface CommissioningBaseline {
  idle: ConditionStats;
  loaded: ConditionStats;
}

export interface MachineSpec {
  model: string;
  install_year: number;
  last_maintenance_date: string;
  maintenance_interval_days: number;
  wear_curve_shape: string;
}

export interface ParamRange {
  min: number;
  max: number;
  step: number;
}

export interface StationSpec {
  id: string;
  name: string;
  zone: Zone;
  sequence_index: number;
  sensors: SensorSpec[];
  acquisition_mode: AcquisitionMode;
  is_inspection_station: boolean;
  cycle_time_nominal_s: number;
  commissioning_baseline: CommissioningBaseline | null;
  changeable_params: Record<string, ParamRange>;
  readable_params: string[];
  machine: MachineSpec;
  cost_per_hour: number;
  value_add_pct: number;
}

export interface StationCoordinate {
  station_id: string;
  x_m: number;
  y_m: number;
}

export interface ConveyorSegment {
  from_station_id: string;
  to_station_id: string;
  distance_m: number;
}

export interface LayoutSpec {
  coordinates: StationCoordinate[];
  segments: ConveyorSegment[];
}

export interface EnvironmentEnvelope {
  temp_min_c: number;
  temp_max_c: number;
  humidity_min_pct: number;
  humidity_max_pct: number;
}

export interface LineSpec {
  plant_name: string;
  site: string;
  stations: StationSpec[];
  layout: LayoutSpec;
  environment_envelope: EnvironmentEnvelope;
}

export interface RunToLearnRequest {
  accuracy_classes: Record<string, string>;
  idle_nominal: Record<string, number>;
  loaded_nominal: Record<string, number>;
  sample_count?: number;
  seed?: number | null;
}

// --- replay -------------------------------------------------------------

export type SensorHealth = "green" | "red" | "not_yet_reporting" | "not_applicable";
export type MachineHealth = "green" | "red";
export type PlaybackMode = "playing" | "paused" | "step";

// Not yet returned by any endpoint the frontend calls -- defined now so the
// design tokens (styles/tokens.ts) can cover the full status vocabulary
// ahead of Predict's SPC/risk views being wired up.
export type SPCState = "in_control" | "out_of_control" | "unknown" | "environment_invalid";
export type RiskLevel = "low" | "medium" | "high" | "unknown_risk";

export interface LatestReading {
  sensor_id: string;
  quantity: string;
  value: number;
  timestamp: string;
}

export interface StationState {
  station_id: string;
  car_id: string | null;
  upstream_buffer_depth: number;
  sensor_health: SensorHealth;
  machine_health: MachineHealth;
  latest_readings: LatestReading[];
}

export interface LineState {
  run_id: string;
  timestamp: string;
  speed_multiplier: number;
  playback_mode: PlaybackMode;
  stations: StationState[];
}

// --- twin -----------------------------------------------------------------

export interface Reading {
  sensor_id: string;
  quantity: string;
  value: number;
  acquisition_mode: string;
}

export interface AmbientConditions {
  temp_c: number;
  humidity_pct: number | null;
}

export interface StationVisit {
  station_id: string;
  entry_time: string;
  exit_time: string;
  readings: Reading[];
  operator_id: string | null;
  handover_flagged: boolean | null;
  machine_wear_state: number;
  ambient_conditions: AmbientConditions;
}

export interface CarTwin {
  car_id: string;
  model_variant: string;
  entry_timestamp: string;
  visits: StationVisit[];
}

export interface RunSummary {
  run_id: string;
}

export type ReplayAction = "load" | "play" | "pause" | "step" | "seek" | "set_speed";

export interface ReplayControlRequest {
  action: ReplayAction;
  run_id?: string;
  timestamp?: string;
  speed_multiplier?: number;
}

// --- role views -------------------------------------------------------------

export type Role =
  | "mirror"
  | "operator"
  | "floor_supervisor"
  | "plant_manager"
  | "leadership"
  | "prediction_ledger";

export interface SPCVerdict {
  station_id: string;
  quantity: string;
  state: SPCState;
  rule_triggered: string | null;
  confidence: number;
  recalibrating: boolean;
  uncertainty_band_multiplier: number;
}

export interface OperatorView {
  station_id: string;
  station_name: string;
  sensor_health: SensorHealth;
  machine_health: MachineHealth;
  latest_readings: LatestReading[];
  commissioning_baseline: CommissioningBaseline | null;
  spc_verdict: SPCVerdict | null;
}

export interface SPCAlarm {
  station_id: string;
  quantity: string;
  state: SPCState;
  rule_triggered: string | null;
  confidence: number;
}

export interface HighRiskCar {
  car_id: string;
  current_station_id: string;
  next_inspection_station_id: string;
  stations_remaining: number;
  risk_level: RiskLevel;
  probability: number | null;
  confidence: number;
}

export type BottleneckState = "starved" | "blocked" | "healthy";

export interface BottleneckForecast {
  station_id: string;
  predicted_state: BottleneckState;
  minutes_to_onset: number | null;
  confidence: number;
  contributing_upstream_station: string | null;
}

export interface FloorSupervisorView {
  line_state: LineState;
  active_alert_station_ids: string[];
  spc_alarms: SPCAlarm[];
  high_risk_cars: HighRiskCar[];
  bottleneck_warnings: BottleneckForecast[];
  issue_assignments: Record<string, string>;
}

export type ApproverRole = "operator" | "floor_supervisor" | "plant_manager" | "leadership";
export type ProposalStatus = "pending" | "approved" | "rejected";

export interface Proposal {
  proposal_id: string;
  station_id: string;
  parameter_name: string;
  current_value: number;
  proposed_value: number;
  rationale: string;
  trace_car_id: string;
  requires_physical_change: boolean;
  next_maintenance_window: string | null;
  status: ProposalStatus;
}

export interface AuditRecord {
  proposal_id: string;
  approver_role: ApproverRole;
  approver_id: string;
  decision: string;
  timestamp: string;
  proposal_snapshot: Proposal;
}

export interface DefectRateByStation {
  station_id: string;
  zone: Zone;
  total_inspections: number;
  fail_count: number;
  fail_rate: number;
}

export interface DefectRateByZone {
  zone: Zone;
  total_inspections: number;
  fail_count: number;
  fail_rate: number;
}

export interface ReworkSummary {
  total_defect_events: number;
  cars_requiring_rework: number;
  total_cars_inspected: number;
  rework_rate: number;
}

export interface RecurringRootCause {
  station_id: string;
  occurrence_count: number;
  example_car_ids: string[];
}

export interface MaintenanceStatus {
  station_id: string;
  machine_model: string;
  maintenance_interval_days: number;
  days_since_maintenance: number;
  days_until_due: number;
  recent_wear_state: number | null;
}

export interface PlantManagerView {
  defect_rate_by_station: DefectRateByStation[];
  defect_rate_by_zone: DefectRateByZone[];
  rework: ReworkSummary;
  recurring_root_causes: RecurringRootCause[];
  maintenance_status: MaintenanceStatus[];
}

export interface CostByZone {
  zone: Zone;
  total_cost_per_hour: number;
  value_added_cost_per_hour: number;
  value_added_ratio: number;
}

export interface SensorRetrofitCandidate {
  station_id: string;
  zone: Zone;
  cost_per_hour: number;
  value_add_pct: number;
  economic_weight: number;
  recurring_defect_occurrences: number;
}

export interface LeadershipView {
  total_cost_per_hour: number;
  total_value_added_cost_per_hour: number;
  value_added_ratio: number;
  cost_by_zone: CostByZone[];
  sensor_retrofit_candidates: SensorRetrofitCandidate[];
}

// --- prediction ledger --------------------------------------------------

export type PredictionOutcome = "pending" | "materialized" | "not_materialized";
export type TrendState = "improving" | "stagnant" | "worsening";

export interface LedgerMetrics {
  sample_size: number;
  true_positive: number;
  false_positive: number;
  true_negative: number;
  false_negative: number;
  precision: number | null;
  recall: number | null;
  false_alarm_rate: number | null;
  trust_score: number | null;
}
