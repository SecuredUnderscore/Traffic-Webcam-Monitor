import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Cpu, FlaskConical } from "lucide-react";
import { api, snapshotUrl } from "../api";
import type { LabResult } from "../types";
import SnapshotView from "../components/SnapshotView";
import { Field, Spinner } from "../components/ui";
import { cx } from "../util";

const GRID_LABEL: Record<number, string> = { 0: "Full frame", 2: "2×2 tiles", 3: "3×3 tiles" };

export default function LabPage() {
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  const cams = useQuery({ queryKey: ["cameras"], queryFn: api.cameras });
  const [source, setSource] = useState<string>("");
  const [url, setUrl] = useState("");
  const [models, setModels] = useState<string[] | null>(null);
  const [grids, setGrids] = useState<number[]>([0, 2]);
  const [devices, setDevices] = useState<string[]>(["cpu"]);
  const [conf, setConf] = useState(0.25);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [out, setOut] = useState<Awaited<ReturnType<typeof api.lab>> | null>(null);
  const [sel, setSel] = useState<number>(0);

  const allModels = meta.data?.models.map((m) => m.id) ?? [];
  const chosenModels = models ?? allModels.filter((m) => !m.endsWith("m"));
  const camsWithImage = cams.data?.filter((c) => c.latest) ?? [];
  const src = source || (camsWithImage[0] ? String(camsWithImage[0].id) : "url");

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      const cam = camsWithImage.find((c) => String(c.id) === src);
      const res = await api.lab({
        ...(src === "url" ? { url } : { snapshot_id: cam?.latest?.id }),
        models: chosenModels, grids, devices, conf, runs: 3,
      });
      setOut(res);
      setSel(0);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  };

  const toggle = <T,>(arr: T[], v: T) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
  const results = (out?.results ?? []).filter((r) => !r.error);
  const maxMs = Math.max(1, ...results.map((r) => r.ms_median ?? 0));
  const cur: LabResult | undefined = results[sel];
  const imgSrc = out?.image.snapshot_id ? snapshotUrl(out.image.snapshot_id, out.image.sha) : out?.image.data_url ?? null;

  return (
    <div className="page">
      <div className="page-head">
        <div className="grow">
          <h1>Detector Lab</h1>
          <div className="sub">Compare models, tiling and hardware on a camera frame</div>
        </div>
      </div>

      <div className="split split-aside-left">
        <div className="col" style={{ gap: 16 }}>
          <div className="card card-pad col" style={{ gap: 16 }}>
            <Field label="Image">
              <select className="select" value={src} onChange={(e) => setSource(e.target.value)}>
                {camsWithImage.map((c) => <option key={c.id} value={c.id}>{c.name} (latest scan)</option>)}
                <option value="url">Image URL…</option>
              </select>
            </Field>
            {src === "url" && <input className="input mono" placeholder="https://…/camera.jpg" value={url} onChange={(e) => setUrl(e.target.value)} />}
            <div className="field">
              <label>Models</label>
              <div className="col" style={{ gap: 8 }}>
                {meta.data?.models.map((m) => (
                  <label key={m.id} className="check">
                    <input type="checkbox" checked={chosenModels.includes(m.id)} onChange={() => setModels(toggle(chosenModels, m.id))} />
                    <span className="mono">{m.id}</span><span className="muted small">{m.size_mb} MB{m.builtin ? "" : " · custom"}</span>
                  </label>
                ))}
              </div>
            </div>
            <div className="field">
              <label>Tiling</label>
              <div className="row wrap">
                {[0, 2, 3].map((g) => (
                  <label key={g} className="check"><input type="checkbox" checked={grids.includes(g)} onChange={() => setGrids(toggle(grids, g))} />{GRID_LABEL[g]}</label>
                ))}
              </div>
            </div>
            <div className="field">
              <label>Hardware</label>
              <div className="row wrap">
                {meta.data?.devices.map((d) => (
                  <label key={d} className="check"><input type="checkbox" checked={devices.includes(d)} onChange={() => setDevices(toggle(devices, d))} />{d.toUpperCase()}</label>
                ))}
              </div>
              {meta.data && !meta.data.devices.includes("cuda") && <div className="hint">GPU not available in this container (CPU image). See README for the GPU build.</div>}
            </div>
            <Field label={`Confidence threshold: ${conf.toFixed(2)}`}>
              <input type="range" min={0.05} max={0.8} step={0.05} value={conf} onChange={(e) => setConf(Number(e.target.value))} />
            </Field>
            <button className="btn primary" onClick={run} disabled={running || !chosenModels.length || !grids.length || (src === "url" && url.length < 8)}>
              {running ? <Spinner size={14} /> : <FlaskConical size={16} />} {running ? "Benchmarking…" : "Run benchmark"}
            </button>
            {error && <div className="callout err"><AlertTriangle size={16} />{error}</div>}
          </div>

          <div className="card">
            <div className="card-head"><Cpu size={16} /><h3>Hardware</h3></div>
            <div className="card-body col small">
              <div className="mono">{meta.data?.cpu} · {meta.data?.cpu_count} threads</div>
              <p className="muted">
                Cameras refresh every 5–20 minutes, so detection runs a few times per minute at most. Small models take
                about 20–200 ms per frame on a modern CPU; a GPU only matters for the largest models with fine tiling.
              </p>
            </div>
          </div>
        </div>

        <div className="col" style={{ gap: 16, minWidth: 0 }}>
          {!out && !running && (
            <div className="card empty-state">
              <FlaskConical size={20} />
              <h2>No results yet</h2>
              <p>
                Choose an image and models, then run the benchmark. Each combination gets a warm-up and 3 timed passes.
                Tiling finds more small, distant vehicles at about 5× the time.
              </p>
            </div>
          )}
          {running && <div className="card card-pad row"><Spinner /> Running {chosenModels.length * grids.length * devices.length} configurations…</div>}
          {out && (
            <>
              <div className="card" style={{ overflow: "hidden" }}>
                <SnapshotView src={imgSrc} width={out.image.width} height={out.image.height} detections={cur?.detections} />
              </div>
              <div className="card" style={{ overflowX: "auto" }}>
                <table className="table">
                  <thead><tr><th>Model</th><th>Tiling</th><th>Device</th><th>Vehicles</th><th>Avg conf.</th><th style={{ width: "34%" }}>Time per frame (median)</th></tr></thead>
                  <tbody>
                    {results.map((r, i) => (
                      <tr key={i} className={cx("clickable", i === sel && "on")} onClick={() => setSel(i)}>
                        <td className="mono">{r.model}</td>
                        <td>{GRID_LABEL[r.grid ?? 0] ?? `${r.grid}×${r.grid}`}</td>
                        <td>{r.device.toUpperCase()}{r.provider && !r.provider.toLowerCase().startsWith(r.device) && <span className="muted small"> ({r.provider})</span>}</td>
                        <td><b>{r.count}</b></td>
                        <td>{r.mean_score != null ? `${Math.round(r.mean_score * 100)}%` : "—"}</td>
                        <td>
                          <div className="row">
                            <div className="bar" style={{ width: `${((r.ms_median ?? 0) / maxMs) * 100}%` }} />
                            <span className="mono nowrap">{r.ms_median?.toFixed(0)} ms</span>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {out.results.filter((r) => r.error).map((r, i) => <div key={i} className="callout err" style={{ margin: 12 }}>{r.model} / {r.device}: {r.error}</div>)}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
