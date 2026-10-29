export type Density = "empty" | "light" | "moderate" | "heavy" | "unknown";
export type Motion = "none" | "stopped" | "slow" | "moving" | "unknown";
export type CameraStatus = "ok" | "stale" | "error" | "paused" | "pending";

export interface Detection {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  score: number;
  label: string;
}

export interface Observation {
  snapshot_id: number;
  zone_id: number;
  ts: string;
  count: number;
  occupancy: number;
  activity: number | null;
  change: number | null;
  stationary: number | null;
  density: Density;
  motion: Motion;
  light_hint: string | null;
}

/** Result of a live preview analysis (not stored). */
export interface ZonePreview extends Omit<Observation, "snapshot_id" | "ts"> {
  detections: number[];
}

export type RuleKind = "density_change" | "motion_change" | "count_threshold" | "activity_threshold";

export interface Rule {
  id: number;
  zone_id: number;
  name: string;
  kind: RuleKind;
  params: Record<string, any>;
  cooldown_min: number;
  enabled: boolean;
  channels: string[];
  last_fired_at: string | null;
}

export type Point = [number, number];

export interface Zone {
  id: number;
  camera_id: number;
  name: string;
  direction: string;
  color: string;
  polygon: Point[];
  enabled: boolean;
  metric: "count" | "activity";
  thresholds: Record<string, number>;
  min_vehicles_for_motion: number;
  rules: Rule[];
  latest: Observation | null;
}

export interface Snapshot {
  id: number;
  camera_id: number;
  ts: string;
  sha: string;
  width: number;
  height: number;
  vehicle_count: number;
  inference_ms: number;
  model_id: string;
  view_score: number | null;
  view_shift: boolean;
  brightness: number;
  detections?: Detection[];
  observations?: Observation[];
}

export interface Camera {
  id: number;
  name: string;
  url: string;
  interval_sec: number;
  enabled: boolean;
  headers: Record<string, string>;
  cache_bust: boolean;
  notes: string;
  model_id: string | null;
  tile_grid: number | null;
  conf: number | null;
  status: CameraStatus;
  last_checked_at: string | null;
  last_new_image_at: string | null;
  last_error: string | null;
  next_check_at: string | null;
  latest: Snapshot | null;
  zones: Zone[];
}

export interface CameraInput {
  name: string;
  url: string;
  interval_sec: number;
  enabled: boolean;
  headers: Record<string, string>;
  cache_bust: boolean;
  notes: string;
  model_id: string | null;
  tile_grid: number | null;
  conf: number | null;
}

export interface TrafficEvent {
  id: number;
  ts: string;
  camera_id: number;
  zone_id: number | null;
  rule_id: number | null;
  camera_name: string | null;
  zone_name: string | null;
  title: string;
  message: string;
  snapshot_id: number | null;
  prev_snapshot_id: number | null;
  delivery: Record<string, any>;
  acknowledged: boolean;
}

export interface Meta {
  version: string;
  models: { id: string; builtin: boolean; size_mb: number }[];
  devices: string[];
  cpu: string;
  cpu_count: number;
}

export type Settings = Record<string, any>;

/** Bytes used in the data directory. effective_limit is lower than limit when the disk is smaller. */
export interface Storage {
  used: number;
  limit: number;
  effective_limit: number;
  snapshots: number;
  database: number;
  other: number;
  disk_free: number;
}

export interface SuggestedZone {
  polygon: Point[];
  name: string;
  color: string;
  area: number;
  direction_hint: "away" | "toward" | null;
  support: number;
}

export interface LabResult {
  model: string;
  device: string;
  provider?: string;
  grid?: number;
  ms_median?: number;
  ms_min?: number;
  count?: number;
  mean_score?: number | null;
  detections?: Detection[];
  error?: string;
}
