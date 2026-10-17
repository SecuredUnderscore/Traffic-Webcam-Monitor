import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, ArrowLeft, Bell, Eye, EyeOff, MousePointer2, Pause, Pencil, Play, Plus, RefreshCw,
  Send, Sparkles, Square, Trash2, Hexagon, Info,
} from "lucide-react";
import { api, snapshotUrl, type ZoneInput } from "../api";
import type { Camera, Point, Rule, SuggestedZone, Zone, ZonePreview } from "../types";
import ZoneEditor, { type Tool } from "../components/ZoneEditor";
import SnapshotView from "../components/SnapshotView";
import CameraForm, { cameraToInput } from "../components/CameraForm";
import RuleForm, { describeRule } from "../components/RuleForm";
import ZoneChart from "../components/ZoneChart";
import { DensityChip, Field, Modal, MotionChip, Spinner, StatusDot, Switch, useNow, useToast } from "../components/ui";
import { cx, DIRECTIONS, fmtInterval, fmtTime, MOTION_LABEL, PALETTE, pct, timeAgo, timeUntil } from "../util";

const toInput = (z: Zone): ZoneInput => ({
  name: z.name, direction: z.direction, color: z.color, polygon: z.polygon, enabled: z.enabled,
  metric: z.metric, thresholds: z.thresholds, min_vehicles_for_motion: z.min_vehicles_for_motion,
});

const DEFAULT_T = { count: { empty: 0, light: 3, moderate: 8 }, activity: { empty: 1.5, light: 6, moderate: 15 } };

function SuggestModal({ cam, onClose, onAdd }: { cam: Camera; onClose: () => void; onAdd: (z: SuggestedZone[]) => Promise<void> }) {
  const q = useQuery({ queryKey: ["suggest", cam.id, cam.latest?.id], queryFn: () => api.suggestZones(cam.id), retry: false });
  const [picked, setPicked] = useState<Record<number, boolean>>({});
  const [names, setNames] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const zones = q.data?.zones ?? [];
  // Regions with only a few sightings are often false detections; offer them unchecked.
  const minSupport = Math.max(3, (q.data?.detections ?? 0) * 0.03);
  const lowSupport = (z: SuggestedZone) => q.data?.method === "detections" && z.support < minSupport;
  useEffect(() => {
    setPicked(Object.fromEntries(zones.map((z, i) => [i, !lowSupport(z)])));
    setNames(Object.fromEntries(zones.map((z, i) => [i, z.name])));
  }, [q.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const chosen = zones.map((z, i) => ({ ...z, name: names[i] ?? z.name })).filter((_, i) => picked[i]);
  return (
    <Modal
      title="Auto-detect traffic lanes"
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={!chosen.length || busy} onClick={async () => { setBusy(true); await onAdd(chosen); }}>
            {busy && <Spinner size={14} />} Add {chosen.length} zone{chosen.length === 1 ? "" : "s"}
          </button>
        </>
      }
    >
      {q.isLoading && <div className="row"><Spinner /> Analyzing where vehicles have appeared…</div>}
      {q.error && <div className="callout err"><AlertTriangle size={16} />{(q.error as Error).message}</div>}
      {q.data && (
        <>
          <div className="callout">
            <Info size={16} />
            <div>
              Built from <b>{q.data.frames}</b> scan{q.data.frames === 1 ? "" : "s"} using {q.data.method === "detections" ? "vehicle detections" : "pixel changes (vehicles too small to detect)"}.
              Suggestions get much better after a few hours of history. Night scans add a direction hint (red taillights = away from camera, white headlights = toward).
              Name each zone by its direction; you can reshape them afterwards.
            </div>
          </div>
          {zones.length === 0 ? (
            <div className="muted">No clear traffic regions yet. Let it collect more scans, or draw zones manually.</div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 300px", gap: 16 }}>
              <SnapshotView
                src={cam.latest ? snapshotUrl(cam.latest.id, cam.latest.sha) : null}
                width={cam.latest?.width ?? 640}
                height={cam.latest?.height ?? 480}
                zones={zones.map((z, i) => ({ id: i, name: names[i] ?? z.name, color: z.color, polygon: z.polygon })).filter((z) => picked[z.id])}
                detections={cam.latest?.detections}
              />
              <div className="col">
                {zones.map((z, i) => (
                  <div key={i} className="row">
                    <input type="checkbox" checked={!!picked[i]} onChange={(e) => setPicked({ ...picked, [i]: e.target.checked })} />
                    <span className="zone-swatch" style={{ background: z.color }} />
                    <input className="input sm" value={names[i] ?? ""} list="dirs" onChange={(e) => setNames({ ...names, [i]: e.target.value })} />
                    {lowSupport(z) && <span className="small muted nowrap" title="Only a few vehicles seen here so far">few sightings</span>}
                  </div>
                ))}
                <datalist id="dirs">{DIRECTIONS.map((d) => <option key={d} value={d} />)}</datalist>
              </div>
            </div>
          )}
        </>
      )}
    </Modal>
  );
}

function RulesCard({ zone, onChanged }: { zone: Zone; onChanged: () => void }) {
  const toast = useToast();
  const [editing, setEditing] = useState<Rule | "new" | null>(null);
  const [testing, setTesting] = useState<number | null>(null);
  const now = useNow(30000);

  const test = async (r: Rule) => {
    setTesting(r.id);
    try {
      const res = await api.testRule(r.id);
      if (res.delivery.note) return toast(res.delivery.note, "error");
      const entries = Object.entries(res.delivery);
      const label = (ch: string) => (ch === "discord" ? "Discord" : "Pushover");
      const msg = entries.map(([ch, v]) =>
        v === "ok" ? `${label(ch)}: sent` : v.startsWith("off") ? `${label(ch)} is switched off in Settings` : `${label(ch)}: ${v}`);
      toast(msg.join(" · "), entries.every(([, v]) => v === "ok") ? "ok" : "error");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setTesting(null);
    }
  };

  return (
    <div className="card">
      <div className="card-head">
        <Bell size={15} />
        <h3 className="grow">Alert rules</h3>
        <button className="btn sm primary" onClick={() => setEditing("new")}><Plus size={14} /> Add rule</button>
      </div>
      <div className="card-body col">
        {zone.rules.length === 0 && <div className="hint">No rules yet. Add one to get notified when this zone's traffic changes.</div>}
        {zone.rules.map((r) => (
          <div key={r.id} className={cx("rule-item", !r.enabled && "disabled")}>
            <div className="row">
              <b className="grow ellipsis">{r.name || r.kind}</b>
              <Switch
                checked={r.enabled}
                onChange={async (en) => {
                  await api.updateRule(r.id, { name: r.name, kind: r.kind, params: r.params, cooldown_min: r.cooldown_min, enabled: en, channels: r.channels });
                  onChanged();
                }}
              />
            </div>
            <div className="small" style={{ color: "var(--text-2)" }}>{describeRule(r)}</div>
            <div className="row small muted">
              <span className="grow">{r.last_fired_at ? `Last fired ${timeAgo(r.last_fired_at, now)}` : "Never fired"} · {r.channels.join(", ") || "no channels"}</span>
              <button className="btn sm icon ghost" title="Send a test alert" onClick={() => test(r)} disabled={testing === r.id}>
                {testing === r.id ? <Spinner size={13} /> : <Send size={13} />}
              </button>
              <button className="btn sm icon ghost" title="Edit" onClick={() => setEditing(r)}><Pencil size={13} /></button>
              <button
                className="btn sm icon ghost"
                title="Delete"
                onClick={async () => {
                  if (!confirm(`Delete rule "${r.name}"?`)) return;
                  await api.deleteRule(r.id);
                  onChanged();
                }}
              >
                <Trash2 size={13} />
              </button>
            </div>
          </div>
        ))}
      </div>
      {editing && (
        <RuleForm
          zone={zone}
          rule={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSave={async (body) => {
            if (editing === "new") await api.createRule(zone.id, body);
            else await api.updateRule(editing.id, body);
            setEditing(null);
            onChanged();
          }}
        />
      )}
    </div>
  );
}

function ZonePanel({
  zone, preview, onSave, onDelete,
}: {
  zone: Zone; preview?: ZonePreview; onSave: (z: ZoneInput) => void; onDelete: () => void;
}) {
  const [v, setV] = useState<ZoneInput>(toInput(zone));
  const first = useRef(true);
  useEffect(() => {
    setV(toInput(zone));
    first.current = true;
  }, [zone.id]); // eslint-disable-line react-hooks/exhaustive-deps
  // Keep geometry in sync with editor drags without clobbering in-progress text edits.
  useEffect(() => setV((x) => ({ ...x, polygon: zone.polygon })), [zone.polygon]);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const t = setTimeout(() => onSave(v), 600);
    return () => clearTimeout(t);
  }, [v.name, v.direction, v.color, v.metric, v.enabled, v.min_vehicles_for_motion, JSON.stringify(v.thresholds)]); // eslint-disable-line react-hooks/exhaustive-deps

  const history = useQuery({ queryKey: ["history", zone.id], queryFn: () => api.zoneHistory(zone.id, 96), refetchInterval: 30000 });
  const t = { ...DEFAULT_T[v.metric], ...v.thresholds };
  const setT = (k: string, val: number) => setV({ ...v, thresholds: { ...t, [k]: val } });
  const p = preview;

  return (
    <div className="card">
      <div className="card-head">
        <span className="zone-swatch" style={{ background: v.color, width: 12, height: 12 }} />
        <h3 className="grow ellipsis">{v.name}</h3>
        <Switch checked={v.enabled} onChange={(en) => setV({ ...v, enabled: en })} title="Zone enabled" />
        <button className="btn sm icon ghost" title="Delete zone" onClick={onDelete}><Trash2 size={14} /></button>
      </div>
      <div className="card-body col" style={{ gap: 14 }}>
        {p && (
          <div className="col" style={{ gap: 8 }}>
            <div className="row wrap">
              <DensityChip value={p.density} />
              <MotionChip value={p.motion} />
              {p.light_hint && <span className="chip">Lights: {p.light_hint === "away" ? "taillights (away)" : "headlights (toward)"}</span>}
            </div>
            <div className="metric-grid">
              <div className="metric"><div className="v">{p.count}</div><div className="k">Vehicles</div></div>
              <div className="metric"><div className="v">{pct(p.occupancy, 0)}</div><div className="k">Occupancy</div></div>
              <div className="metric" title="Share of the zone that differs from the learned empty road"><div className="v">{pct(p.activity)}</div><div className="k">Activity</div></div>
              <div className="metric" title="Share of the zone that changed since the previous scan"><div className="v">{pct(p.change, 0)}</div><div className="k">Changed</div></div>
              <div className="metric" title="Share of vehicles still in the same spot as the previous scan"><div className="v">{p.stationary == null ? "—" : `${Math.round(p.stationary * 100)}%`}</div><div className="k">Stationary</div></div>
              <div className="metric"><div className="v" style={{ fontSize: 13, paddingTop: 3 }}>{MOTION_LABEL[p.motion]}</div><div className="k">Flow</div></div>
            </div>
          </div>
        )}
        <div className="form-grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <Field label="Name"><input className="input" value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} /></Field>
          <Field label="Direction">
            <input className="input" list="dir-list" value={v.direction} placeholder="NB, SB…" onChange={(e) => setV({ ...v, direction: e.target.value })} />
            <datalist id="dir-list">{DIRECTIONS.map((d) => <option key={d} value={d} />)}</datalist>
          </Field>
        </div>
        <div className="field">
          <label>Color</label>
          <div className="row">
            {PALETTE.map((c) => (
              <button key={c} onClick={() => setV({ ...v, color: c })} title={c}
                style={{ width: 22, height: 22, borderRadius: 6, background: c, border: v.color === c ? "2px solid white" : "2px solid transparent", cursor: "pointer" }} />
            ))}
          </div>
        </div>
        <div className="field">
          <label>Measure traffic by</label>
          <div className="seg">
            <button className={cx(v.metric === "count" && "on")} onClick={() => setV({ ...v, metric: "count", thresholds: {} })}>Vehicle count</button>
            <button className={cx(v.metric === "activity" && "on")} onClick={() => setV({ ...v, metric: "activity", thresholds: {} })}>Pixel activity</button>
          </div>
          <div className="hint">
            {v.metric === "count"
              ? "Counts detected vehicles. Best when vehicles are at least ~15 px tall."
              : "Compares the zone with the learned empty road. Works for distant/tiny vehicles; needs ~3 scans of history first."}
          </div>
        </div>
        <div className="field">
          <label>Level thresholds ({v.metric === "count" ? "vehicles" : "% of zone"}, upper bound of each)</label>
          <div className="row">
            {(["empty", "light", "moderate"] as const).map((k) => (
              <div key={k} className="col grow" style={{ gap: 3 }}>
                <span className={cx("small", `d-${k}`)} style={{ background: "none", border: 0 }}>{k}</span>
                <input className="input sm" type="number" step={v.metric === "count" ? 1 : 0.5} min={0} value={t[k]} onChange={(e) => setT(k, Number(e.target.value))} />
              </div>
            ))}
            <div className="col grow" style={{ gap: 3 }}>
              <span className="small d-heavy" style={{ background: "none", border: 0 }}>heavy</span>
              <div className="input sm muted" style={{ display: "flex", alignItems: "center" }}>&gt; {t.moderate}</div>
            </div>
          </div>
        </div>
        <Field label="Min. vehicles to judge flow" hint="Stopped/moving is only decided when at least this many vehicles are detected (pixel-activity zones compare pixels instead).">
          <input className="input sm" type="number" min={1} max={20} style={{ width: 90 }} value={v.min_vehicles_for_motion} onChange={(e) => setV({ ...v, min_vehicles_for_motion: Number(e.target.value) })} />
        </Field>
        <div className="field">
          <label>Recent history</label>
          {history.data ? <ZoneChart data={history.data} metric={v.metric} /> : <Spinner />}
        </div>
      </div>
    </div>
  );
}

export default function CameraPage() {
  const id = Number(useParams().id);
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const now = useNow(1000);
  const cam = useQuery({ queryKey: ["camera", id], queryFn: () => api.camera(id), refetchInterval: 10000 });
  const snaps = useQuery({ queryKey: ["snapshots", id, cam.data?.latest?.id], queryFn: () => api.snapshots(id, 48), enabled: !!cam.data });
  const [tool, setTool] = useState<Tool>("select");
  const [selected, setSelected] = useState<number | null>(null);
  const [showDets, setShowDets] = useState(true);
  const [viewSnap, setViewSnap] = useState<number | null>(null);
  const [editingCam, setEditingCam] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [checking, setChecking] = useState(false);

  const c = cam.data;
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["camera", id] });
    qc.invalidateQueries({ queryKey: ["cameras"] });
  };

  const zoneKey = JSON.stringify(c?.zones.map((z) => [z.id, z.polygon, z.metric, z.thresholds, z.min_vehicles_for_motion, z.enabled]));
  const preview = useQuery({
    queryKey: ["preview", id, c?.latest?.id, zoneKey],
    queryFn: () =>
      api.preview(id, c!.zones.filter((z) => z.enabled).map((z) => ({ id: z.id, polygon: z.polygon, metric: z.metric, thresholds: z.thresholds, min_vehicles_for_motion: z.min_vehicles_for_motion }))),
    enabled: !!c?.latest && (c?.zones.length ?? 0) > 0,
    retry: false,
  });
  const historical = useQuery({ queryKey: ["snapshot", viewSnap], queryFn: () => api.snapshot(viewSnap!), enabled: viewSnap != null });

  useEffect(() => {
    if (selected != null && c && !c.zones.find((z) => z.id === selected)) setSelected(null);
  }, [c, selected]);

  const previewMap = useMemo(() => Object.fromEntries((preview.data?.zones ?? []).map((z) => [z.zone_id, z])), [preview.data]);
  const histMap = useMemo(() => Object.fromEntries((historical.data?.observations ?? []).map((o) => [o.zone_id, o])), [historical.data]);

  if (cam.isLoading) return <div className="page"><Spinner /></div>;
  if (!c) return <div className="page">Camera not found. <Link to="/">Back</Link></div>;

  const shown = viewSnap != null && historical.data ? historical.data : c.latest;
  const results = viewSnap != null ? histMap : previewMap;
  const zone = c.zones.find((z) => z.id === selected) ?? null;

  const createZone = async (polygon: Point[]) => {
    const n = c.zones.length;
    const z = await api.createZone(c.id, {
      name: `Zone ${n + 1}`, direction: "", color: PALETTE[n % PALETTE.length], polygon, enabled: true,
      metric: (c.latest?.width ?? 1000) < 500 && (c.latest?.vehicle_count ?? 0) === 0 ? "activity" : "count",
      thresholds: {}, min_vehicles_for_motion: 2,
    });
    refresh();
    setSelected(z.id);
  };

  const saveZone = async (zid: number, body: ZoneInput) => {
    // Optimistic update so the editor doesn't snap back while the request is in flight.
    qc.setQueryData<Camera>(["camera", id], (old) => old && { ...old, zones: old.zones.map((z) => (z.id === zid ? { ...z, ...body } : z)) });
    try {
      await api.updateZone(zid, body);
    } catch (e: any) {
      toast(e.message, "error");
    }
    refresh();
  };

  const check = async () => {
    setChecking(true);
    try {
      const r = await api.checkNow(c.id);
      const st = r.result.status;
      toast(st === "new" ? `New image analyzed${r.result.events?.length ? ` · ${r.result.events.length} alert(s) fired` : ""}` : st === "unchanged" ? "Camera hasn't published a new image yet" : `Error: ${r.result.error}`, st === "error" ? "error" : st === "new" ? "ok" : "info");
      setViewSnap(null);
      refresh();
    } finally {
      setChecking(false);
    }
  };

  const toggleEnabled = async () => {
    await api.updateCamera(c.id, { ...cameraToInput(c), enabled: !c.enabled });
    refresh();
  };

  return (
    <div className="page">
      <div className="page-head">
        <Link to="/" className="btn ghost icon"><ArrowLeft size={18} /></Link>
        <div className="grow" style={{ minWidth: 0 }}>
          <div className="row"><h1 className="ellipsis">{c.name}</h1><StatusDot status={c.status} withText /></div>
          <div className="sub row wrap" style={{ gap: 14 }}>
            <span>Checks every {fmtInterval(c.interval_sec)}</span>
            <span>New image {timeAgo(c.last_new_image_at, now)}</span>
            {c.enabled && <span>Next check in {timeUntil(c.next_check_at, now)}</span>}
            {c.latest && <span className="mono">{c.latest.width}×{c.latest.height} · {c.latest.model_id} · {c.latest.inference_ms.toFixed(0)} ms</span>}
          </div>
        </div>
        <button className="btn" onClick={check} disabled={checking}>{checking ? <Spinner size={14} /> : <RefreshCw size={14} />} Check now</button>
        <button className="btn" onClick={toggleEnabled}>{c.enabled ? <><Pause size={14} /> Pause</> : <><Play size={14} /> Resume</>}</button>
        <button className="btn" onClick={() => setEditingCam(true)}><Pencil size={14} /> Edit</button>
        <button
          className="btn danger icon"
          title="Delete camera"
          onClick={async () => {
            if (!confirm(`Delete "${c.name}" with all its zones, rules, history and events?`)) return;
            await api.deleteCamera(c.id);
            qc.invalidateQueries({ queryKey: ["cameras"] });
            nav("/");
          }}
        >
          <Trash2 size={15} />
        </button>
      </div>

      {c.last_error && <div className="callout err" style={{ marginBottom: 14 }}><AlertTriangle size={16} /> Last check failed: {c.last_error}</div>}
      {c.latest?.view_shift && viewSnap == null && (
        <div className="callout warn" style={{ marginBottom: 14 }}>
          <AlertTriangle size={16} /> The camera's view changed in the latest image (it may have been panned or zoomed). Alerts are paused for this scan. If the new view is permanent, redraw the zones.
        </div>
      )}

      <div className="camera-layout">
        <div className="col" style={{ gap: 12, minWidth: 0 }}>
          <div className="toolbar">
            <div className="seg">
              <button className={cx(tool === "select" && "on")} onClick={() => setTool("select")} title="Select & edit zones"><MousePointer2 size={14} /> Select</button>
              <button className={cx(tool === "rect" && "on")} onClick={() => setTool("rect")} title="Draw a rectangle zone"><Square size={14} /> Box</button>
              <button className={cx(tool === "poly" && "on")} onClick={() => setTool("poly")} title="Draw a polygon zone"><Hexagon size={14} /> Polygon</button>
            </div>
            <button className="btn sm" onClick={() => setSuggesting(true)} disabled={!c.latest}><Sparkles size={14} /> Auto-detect lanes</button>
            <span className="spacer" />
            <button className={cx("btn sm", showDets && "active")} onClick={() => setShowDets(!showDets)}>
              {showDets ? <Eye size={14} /> : <EyeOff size={14} />} Vehicles {shown?.vehicle_count != null && `(${shown.vehicle_count})`}
            </button>
          </div>

          {viewSnap != null && historical.data && (
            <div className="callout">
              <Info size={16} />
              <span className="grow">Viewing the scan from <b>{fmtTime(historical.data.ts)}</b> with the states recorded at the time.</span>
              <button className="btn sm" onClick={() => setViewSnap(null)}>Back to latest</button>
            </div>
          )}

          <ZoneEditor
            src={shown ? snapshotUrl(shown.id, shown.sha) : null}
            width={shown?.width ?? 640}
            height={shown?.height ?? 480}
            zones={c.zones.filter((z) => z.enabled || z.id === selected)}
            results={results}
            detections={shown?.detections}
            showDetections={showDets}
            selectedId={selected}
            tool={tool}
            onSelect={setSelected}
            onChange={(zid, polygon) => {
              const z = c.zones.find((x) => x.id === zid)!;
              saveZone(zid, { ...toInput(z), polygon });
            }}
            onCreate={createZone}
            onToolDone={() => setTool("select")}
          />
          <div className="hint">
            {tool === "rect" && "Drag on the image to draw a box around one direction of travel."}
            {tool === "poly" && "Click to place points around the lanes. Click the first point or press Enter to finish · Backspace removes the last point · Esc cancels."}
            {tool === "select" && "Click a zone to edit it. Drag corners to reshape, drag the small midpoint dots to add corners, double-click a corner to remove it, drag inside to move."}
          </div>

          <div className="card">
            <div className="card-head"><h3 className="grow">Recent scans</h3><span className="small muted">{snaps.data?.length ?? 0} stored</span></div>
            <div className="card-body">
              <div className="filmstrip">
                {snaps.data?.map((s) => (
                  <div key={s.id} className={cx("film", (viewSnap ?? c.latest?.id) === s.id && "on")} onClick={() => setViewSnap(s.id === c.latest?.id ? null : s.id)} title={`${s.vehicle_count} vehicles`}>
                    <img src={snapshotUrl(s.id, s.sha)} alt="" loading="lazy" />
                    <div className="t">{fmtTime(s.ts)} · {s.vehicle_count}</div>
                    {s.view_shift && <AlertTriangle size={13} className="shift" color="#fde047" />}
                  </div>
                ))}
                {snaps.data?.length === 0 && <div className="hint">No scans yet. Press “Check now”.</div>}
              </div>
            </div>
          </div>
        </div>

        <div className="side-panel">
          <div className="card">
            <div className="card-head"><h3 className="grow">Zones</h3><span className="small muted">{c.zones.length}</span></div>
            <div style={{ padding: 6 }}>
              {c.zones.length === 0 && (
                <div className="hint" style={{ padding: 10 }}>
                  Draw a <b>Box</b> or <b>Polygon</b> around each direction of traffic (e.g. NB lanes and SB lanes), or try <b>Auto-detect lanes</b>.
                </div>
              )}
              {c.zones.map((z) => {
                const r = results[z.id];
                return (
                  <div key={z.id} className={cx("zone-item", selected === z.id && "selected")} onClick={() => setSelected(z.id)} style={{ opacity: z.enabled ? 1 : 0.5 }}>
                    <span className="zone-swatch" style={{ background: z.color }} />
                    <div className="grow" style={{ minWidth: 0 }}>
                      <div className="ellipsis" style={{ fontWeight: 500 }}>{z.name} {z.direction && <span className="muted small">· {z.direction}</span>}</div>
                      <div className="small muted">{z.rules.length} rule{z.rules.length === 1 ? "" : "s"} · {z.metric === "count" ? "vehicle count" : "activity"}</div>
                    </div>
                    {r && <span className="mono small">{z.metric === "count" ? r.count : pct(r.activity)}</span>}
                    {r && <DensityChip value={r.density} />}
                  </div>
                );
              })}
            </div>
          </div>

          {zone && (
            <>
              <ZonePanel
                key={zone.id}
                zone={zone}
                preview={viewSnap == null ? previewMap[zone.id] : (histMap[zone.id] as any)}
                onSave={(body) => saveZone(zone.id, body)}
                onDelete={async () => {
                  if (!confirm(`Delete zone "${zone.name}" and its rules?`)) return;
                  await api.deleteZone(zone.id);
                  setSelected(null);
                  refresh();
                }}
              />
              <RulesCard zone={zone} onChanged={refresh} />
            </>
          )}
          {!zone && c.zones.length > 0 && <div className="hint" style={{ padding: "0 4px" }}>Select a zone to edit its settings and alert rules.</div>}
        </div>
      </div>

      {editingCam && <CameraForm camera={c} onClose={() => setEditingCam(false)} onSaved={() => { setEditingCam(false); refresh(); }} />}
      {suggesting && (
        <SuggestModal
          cam={c}
          onClose={() => setSuggesting(false)}
          onAdd={async (zs) => {
            for (const z of zs) {
              await api.createZone(c.id, {
                name: z.name, direction: z.direction_hint === "away" ? "Away from camera" : z.direction_hint === "toward" ? "Toward camera" : "",
                color: z.color, polygon: z.polygon, enabled: true, metric: "count", thresholds: {}, min_vehicles_for_motion: 2,
              });
            }
            setSuggesting(false);
            refresh();
          }}
        />
      )}
    </div>
  );
}
