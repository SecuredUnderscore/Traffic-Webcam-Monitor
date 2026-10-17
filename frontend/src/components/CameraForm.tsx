import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Plus, Trash2, Zap } from "lucide-react";
import { api } from "../api";
import type { Camera, CameraInput } from "../types";
import { Field, Modal, Spinner, Switch } from "./ui";

const INTERVALS = [60, 120, 300, 600, 900, 1200, 1800];

export function cameraToInput(c?: Camera | null): CameraInput {
  return {
    name: c?.name ?? "",
    url: c?.url ?? "",
    interval_sec: c?.interval_sec ?? 300,
    enabled: c?.enabled ?? true,
    headers: c?.headers ?? {},
    cache_bust: c?.cache_bust ?? false,
    notes: c?.notes ?? "",
    model_id: c?.model_id ?? null,
    tile_grid: c?.tile_grid ?? null,
    conf: c?.conf ?? null,
  };
}

export default function CameraForm({
  camera,
  onClose,
  onSaved,
}: {
  camera?: Camera | null;
  onClose: () => void;
  onSaved: (c: Camera) => void;
}) {
  const [v, setV] = useState<CameraInput>(cameraToInput(camera));
  const [headers, setHeaders] = useState<[string, string][]>(Object.entries(camera?.headers ?? {}));
  const [probe, setProbe] = useState<Awaited<ReturnType<typeof api.probe>> | null>(null);
  const [probing, setProbing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  const set = <K extends keyof CameraInput>(k: K, val: CameraInput[K]) => setV((x) => ({ ...x, [k]: val }));
  const headerObj = () => Object.fromEntries(headers.filter(([k]) => k.trim()).map(([k, val]) => [k.trim(), val]));

  const runProbe = async () => {
    setProbing(true);
    setProbe(null);
    try {
      setProbe(await api.probe(v.url, headerObj(), v.cache_bust));
    } catch (e: any) {
      setProbe({ ok: false, error: e.message });
    } finally {
      setProbing(false);
    }
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    const body = { ...v, headers: headerObj() };
    try {
      onSaved(camera ? await api.updateCamera(camera.id, body) : await api.createCamera(body));
    } catch (e: any) {
      setError(e.message);
      setSaving(false);
    }
  };

  const customInterval = !INTERVALS.includes(v.interval_sec);

  return (
    <Modal
      title={camera ? "Edit camera" : "Add camera"}
      onClose={onClose}
      wide
      footer={
        <>
          {error && <span className="small" style={{ color: "#fca5a5", marginRight: "auto" }}>{error}</span>}
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={save} disabled={saving || !v.name.trim() || v.url.length < 8}>
            {saving && <Spinner size={14} />} {camera ? "Save changes" : "Add camera"}
          </button>
        </>
      }
    >
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 340px", gap: 20 }}>
        <div className="col" style={{ gap: 14 }}>
          <Field label="Name">
            <input className="input" value={v.name} autoFocus placeholder="I-405 @ SR 167" onChange={(e) => set("name", e.target.value)} />
          </Field>
          <Field label="Image URL" hint="Direct link to the camera's JPEG/PNG still image.">
            <div className="row">
              <input
                className="input mono"
                value={v.url}
                placeholder="https://images.example-dot.gov/cam/123.jpg"
                onChange={(e) => {
                  set("url", e.target.value);
                  setProbe(null);
                }}
              />
              <button className="btn" onClick={runProbe} disabled={probing || v.url.length < 8}>
                {probing ? <Spinner size={14} /> : <Zap size={14} />} Test
              </button>
            </div>
          </Field>
          <Field
            label="Check for a new image every"
            hint="The camera's own refresh rate is the useful minimum. Unchanged images are skipped automatically, so checking a bit faster than the camera updates is fine."
          >
            <div className="row">
              <select
                className="select"
                value={customInterval ? "custom" : v.interval_sec}
                onChange={(e) => set("interval_sec", e.target.value === "custom" ? 240 : Number(e.target.value))}
              >
                {INTERVALS.map((s) => (
                  <option key={s} value={s}>{s < 60 ? `${s} seconds` : `${s / 60} minutes`}</option>
                ))}
                <option value="custom">Custom…</option>
              </select>
              {customInterval && (
                <input
                  className="input"
                  type="number"
                  min={15}
                  style={{ width: 120 }}
                  value={v.interval_sec}
                  onChange={(e) => set("interval_sec", Number(e.target.value))}
                />
              )}
              {customInterval && <span className="muted small">sec</span>}
            </div>
          </Field>
          <div className="row" style={{ gap: 20 }}>
            <label className="check">
              <Switch checked={v.enabled} onChange={(x) => set("enabled", x)} /> Monitoring enabled
            </label>
            <label className="check" title="Appends ?_tw=<time> so caches/CDNs return the newest image">
              <input type="checkbox" checked={v.cache_bust} onChange={(e) => set("cache_bust", e.target.checked)} /> Cache-busting
            </label>
          </div>

          <details>
            <summary className="label" style={{ cursor: "pointer" }}>Advanced: request headers & detector overrides</summary>
            <div className="col" style={{ gap: 14, marginTop: 12 }}>
              <div className="field">
                <label>HTTP headers</label>
                <div className="hint">Some camera sites require a Referer or a browser User-Agent.</div>
                {headers.map(([k, val], i) => (
                  <div className="row" key={i}>
                    <input
                      className="input sm mono"
                      placeholder="Referer"
                      value={k}
                      onChange={(e) => setHeaders((h) => h.map((x, j) => (j === i ? [e.target.value, x[1]] : x)))}
                    />
                    <input
                      className="input sm mono"
                      placeholder="https://…"
                      value={val}
                      onChange={(e) => setHeaders((h) => h.map((x, j) => (j === i ? [x[0], e.target.value] : x)))}
                    />
                    <button className="btn sm icon ghost" onClick={() => setHeaders((h) => h.filter((_, j) => j !== i))}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
                <div>
                  <button className="btn sm" onClick={() => setHeaders((h) => [...h, ["", ""]])}>
                    <Plus size={14} /> Add header
                  </button>
                </div>
              </div>
              <div className="form-grid">
                <Field label="Model">
                  <select className="select" value={v.model_id ?? ""} onChange={(e) => set("model_id", e.target.value || null)}>
                    <option value="">Use global default</option>
                    {meta.data?.models.map((m) => <option key={m.id} value={m.id}>{m.id}</option>)}
                  </select>
                </Field>
                <Field label="Tiling" hint="Tiles help with small/distant vehicles.">
                  <select
                    className="select"
                    value={v.tile_grid ?? ""}
                    onChange={(e) => set("tile_grid", e.target.value === "" ? null : Number(e.target.value))}
                  >
                    <option value="">Use global default</option>
                    <option value={0}>Off (full frame)</option>
                    <option value={2}>2×2 tiles</option>
                    <option value={3}>3×3 tiles</option>
                  </select>
                </Field>
                <Field label="Confidence">
                  <input
                    className="input"
                    type="number"
                    step={0.05}
                    min={0.05}
                    max={0.9}
                    placeholder="Global default"
                    value={v.conf ?? ""}
                    onChange={(e) => set("conf", e.target.value === "" ? null : Number(e.target.value))}
                  />
                </Field>
              </div>
              <Field label="Notes">
                <textarea className="input" rows={2} value={v.notes} onChange={(e) => set("notes", e.target.value)} />
              </Field>
            </div>
          </details>
        </div>

        <div className="col">
          <div className="label">Preview</div>
          <div className="card" style={{ overflow: "hidden", minHeight: 200, display: "grid", placeItems: "center" }}>
            {probing && <Spinner />}
            {!probing && !probe && <div className="muted small" style={{ padding: 20, textAlign: "center" }}>Press <b>Test</b> to fetch the image.</div>}
            {probe?.ok && <img src={probe.image} style={{ width: "100%", display: "block" }} alt="" />}
            {probe && !probe.ok && (
              <div className="callout err" style={{ margin: 12 }}>
                <AlertTriangle size={16} /> {probe.error}
              </div>
            )}
          </div>
          {probe?.ok && (
            <div className="row small" style={{ color: "#86efac" }}>
              <CheckCircle2 size={14} /> {probe.width}×{probe.height} · {((probe.bytes ?? 0) / 1024).toFixed(0)} KB
            </div>
          )}
          {probe?.ok && (probe.width ?? 0) < 500 && (
            <div className="hint">Low-resolution camera: distant vehicles may be too small to detect. Use 2×2 tiling, or switch far-away zones to the <b>activity</b> metric.</div>
          )}
        </div>
      </div>
    </Modal>
  );
}
