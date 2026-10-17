import type {
  Camera,
  CameraInput,
  LabResult,
  Meta,
  Observation,
  Point,
  Rule,
  Settings,
  Snapshot,
  SuggestedZone,
  TrafficEvent,
  Zone,
  ZonePreview,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") msg = data.detail;
      else if (Array.isArray(data.detail)) msg = data.detail.map((d: any) => d.msg).join("; ");
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export type ZoneInput = Omit<Zone, "id" | "camera_id" | "rules" | "latest">;
export type RuleInput = Omit<Rule, "id" | "zone_id" | "last_fired_at">;

export const api = {
  meta: () => req<Meta>("GET", "/api/meta"),
  settings: () => req<Settings>("GET", "/api/settings"),
  saveSettings: (s: Settings) => req<Settings>("PUT", "/api/settings", s),
  testChannel: (ch: "discord" | "pushover", s: Settings) =>
    req<{ result: string }>("POST", `/api/settings/test/${ch}`, s),
  cleanup: () => req<Record<string, number>>("POST", "/api/maintenance/cleanup"),

  cameras: () => req<Camera[]>("GET", "/api/cameras"),
  camera: (id: number) => req<Camera>("GET", `/api/cameras/${id}`),
  createCamera: (c: CameraInput) => req<Camera>("POST", "/api/cameras", c),
  updateCamera: (id: number, c: CameraInput) => req<Camera>("PUT", `/api/cameras/${id}`, c),
  deleteCamera: (id: number) => req<{ ok: boolean }>("DELETE", `/api/cameras/${id}`),
  probe: (url: string, headers: Record<string, string>, cache_bust: boolean) =>
    req<{ ok: boolean; error?: string; width?: number; height?: number; bytes?: number; image?: string }>(
      "POST",
      "/api/cameras/probe",
      { url, headers, cache_bust },
    ),
  checkNow: (id: number) =>
    req<{ result: { status: string; error?: string; events?: number[] }; camera: Camera }>(
      "POST",
      `/api/cameras/${id}/check`,
    ),
  snapshots: (id: number, limit = 48) => req<Snapshot[]>("GET", `/api/cameras/${id}/snapshots?limit=${limit}`),
  snapshot: (id: number) => req<Snapshot>("GET", `/api/snapshots/${id}`),
  preview: (id: number, zones: { id: number; polygon: Point[]; metric: string; thresholds: Record<string, number>; min_vehicles_for_motion: number }[]) =>
    req<{ snapshot_id: number; view_shift: boolean; zones: ZonePreview[] }>("POST", `/api/cameras/${id}/preview`, { zones }),
  suggestZones: (id: number) =>
    req<{ zones: SuggestedZone[]; method: string; frames: number; detections?: number }>("POST", `/api/cameras/${id}/suggest-zones`),

  createZone: (camId: number, z: ZoneInput) => req<Zone>("POST", `/api/cameras/${camId}/zones`, z),
  updateZone: (id: number, z: ZoneInput) => req<Zone>("PUT", `/api/zones/${id}`, z),
  deleteZone: (id: number) => req<{ ok: boolean }>("DELETE", `/api/zones/${id}`),
  zoneHistory: (id: number, limit = 96) => req<Observation[]>("GET", `/api/zones/${id}/history?limit=${limit}`),

  createRule: (zoneId: number, r: RuleInput) => req<Rule>("POST", `/api/zones/${zoneId}/rules`, r),
  updateRule: (id: number, r: RuleInput) => req<Rule>("PUT", `/api/rules/${id}`, r),
  deleteRule: (id: number) => req<{ ok: boolean }>("DELETE", `/api/rules/${id}`),
  testRule: (id: number) => req<{ delivery: Record<string, string> }>("POST", `/api/rules/${id}/test`),

  events: (cameraId?: number, limit = 100) =>
    req<TrafficEvent[]>("GET", `/api/events?limit=${limit}${cameraId ? `&camera_id=${cameraId}` : ""}`),
  unread: () => req<{ count: number }>("GET", "/api/events/unread"),
  ack: (id: number) => req<{ ok: boolean }>("POST", `/api/events/${id}/ack`),
  ackAll: () => req<{ ok: boolean }>("POST", "/api/events/ack-all"),
  deleteEvent: (id: number) => req<{ ok: boolean }>("DELETE", `/api/events/${id}`),

  lab: (body: { snapshot_id?: number; url?: string; models: string[]; grids: number[]; devices: string[]; conf: number; runs: number }) =>
    req<{ image: { snapshot_id?: number; sha?: string; data_url?: string; width: number; height: number }; results: LabResult[] }>(
      "POST",
      "/api/lab/run",
      body,
    ),
};

/** Pass the snapshot's sha so the URL is unique to that image content and safe to cache. */
export const snapshotUrl = (id: number, sha?: string) => `/api/snapshots/${id}/image${sha ? `?v=${sha}` : ""}`;
export const annotatedUrl = (id: number, zone?: number | null) =>
  `/api/snapshots/${id}/annotated${zone ? `?zone=${zone}` : ""}`;
