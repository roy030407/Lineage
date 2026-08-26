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

// --- replay -------------------------------------------------------------

export type SensorHealth = "green" | "red" | "not_applicable";
export type MachineHealth = "green" | "red";
export type PlaybackMode = "playing" | "paused" | "step";

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

export interface OperatorView {
  station_id: string;
  station_name: string;
  sensor_health: SensorHealth;
  machine_health: MachineHealth;
  latest_readings: LatestReading[];
  commissioning_baseline: CommissioningBaseline | null;
}

export interface LineSummary {
  occupied_station_count: number;
  alarm_station_count: number;
  average_upstream_buffer_depth: number;
}

export interface FloorSupervisorView {
  line_state: LineState;
  active_alert_station_ids: string[];
}

export interface PlantManagerView {
  line_state: LineState;
  summary: LineSummary;
}

export interface LeadershipView {
  summary: LineSummary;
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
