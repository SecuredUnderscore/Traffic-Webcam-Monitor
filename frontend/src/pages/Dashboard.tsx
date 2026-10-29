import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Camera as CameraIcon, Plus, RefreshCw } from "lucide-react";
import { api, snapshotUrl } from "../api";
import type { Camera } from "../types";
import SnapshotView from "../components/SnapshotView";
import CameraForm from "../components/CameraForm";
import { DensityChip, MotionChip, Spinner, StatusBadge, useNow, useToast } from "../components/ui";
import { fmtInterval, timeAgo, timeUntil } from "../util";

function CameraCard({ cam, now }: { cam: Camera; now: number }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [checking, setChecking] = useState(false);
  const results = Object.fromEntries(cam.zones.filter((z) => z.latest).map((z) => [z.id, z.latest!]));
  const rules = cam.zones.reduce((n, z) => n + z.rules.filter((r) => r.enabled).length, 0);
  const zones = cam.zones.filter((z) => z.enabled);

  const check = async () => {
    setChecking(true);
    try {
      const r = await api.checkNow(cam.id);
      const st = r.result.status;
      toast(st === "new" ? "New image analyzed" : st === "unchanged" ? "No new image yet" : `Error: ${r.result.error}`, st === "error" ? "error" : "info");
      qc.invalidateQueries({ queryKey: ["cameras"] });
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="card cam-card">
      <Link to={`/cameras/${cam.id}`} className="cover" aria-label={`Open ${cam.name}`}>
        <SnapshotView
          src={cam.latest ? snapshotUrl(cam.latest.id, cam.latest.sha) : null}
          width={cam.latest?.width ?? 640}
          height={cam.latest?.height ?? 480}
          zones={zones}
          results={results}
          detections={cam.latest?.detections}
          showLabels={false}
        />
      </Link>
      <div className="meta">
        <div className="row">
          <Link to={`/cameras/${cam.id}`} className="cam-title grow ellipsis">{cam.name}</Link>
          <StatusBadge status={cam.status} />
          <button className="btn sm icon ghost" title="Check now" aria-label="Check now" onClick={check} disabled={checking}>
            {checking ? <Spinner size={14} /> : <RefreshCw size={14} />}
          </button>
        </div>

        {cam.zones.length === 0 ? (
          <p className="small muted">No zones yet. <Link to={`/cameras/${cam.id}`}>Draw zones</Link> to start detecting changes.</p>
        ) : zones.length === 0 ? (
          <p className="small muted">{cam.zones.length === 1 ? "Its zone is" : `All ${cam.zones.length} zones are`} switched off.</p>
        ) : (
          <div className="zone-rows">
            {zones.map((z) => (
              <div key={z.id} className="zone-line">
                <span className="zone-swatch" style={{ background: z.color }} />
                <span className="ellipsis">{z.name}</span>
                {z.latest ? (
                  <>
                    <span className="mono muted">{z.metric === "count" ? `${z.latest.count} veh` : `${(z.latest.activity ?? 0).toFixed(1)}%`}</span>
                    <DensityChip value={z.latest.density} />
                    <MotionChip value={z.latest.motion} hideNone />
                  </>
                ) : (
                  <span className="small muted" style={{ gridColumn: "span 3" }}>Waiting for scan</span>
                )}
              </div>
            ))}
          </div>
        )}

        {cam.last_error && cam.status === "error" && (
          <div className="callout err small"><AlertTriangle size={14} /> {cam.last_error}</div>
        )}

        <div className="cam-foot">
          <span>Image {cam.latest ? timeAgo(cam.latest.ts, now) : "none yet"}</span>
          <span>Every {fmtInterval(cam.interval_sec)}</span>
          {cam.enabled && <span>Next in {timeUntil(cam.next_check_at, now)}</span>}
          <span className="spacer" />
          <span>{rules} rule{rules === 1 ? "" : "s"}</span>
        </div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const now = useNow(1000);
  const [adding, setAdding] = useState(false);
  const cams = useQuery({ queryKey: ["cameras"], queryFn: api.cameras, refetchInterval: 10000 });
  const total = cams.data?.length ?? 0;
  const live = cams.data?.filter((c) => c.status === "ok").length ?? 0;

  return (
    <div className="page">
      <div className="page-head">
        <div className="grow">
          <h1>Cameras</h1>
          {total > 0 && <div className="sub">{live} of {total} live</div>}
        </div>
        <button className="btn primary" onClick={() => setAdding(true)}><Plus size={16} /> Add camera</button>
      </div>

      {cams.isLoading && <Spinner />}
      {cams.data?.length === 0 && (
        <div className="card empty-state">
          <CameraIcon size={20} />
          <h2>No cameras yet</h2>
          <p>Add a link to a traffic camera's still image. Traffic Webcam Monitor checks it on your schedule and alerts you when traffic in a zone changes.</p>
          <button className="btn primary" onClick={() => setAdding(true)}><Plus size={16} /> Add camera</button>
        </div>
      )}
      <div className="cam-grid">
        {cams.data?.map((c) => <CameraCard key={c.id} cam={c} now={now} />)}
      </div>

      {adding && (
        <CameraForm
          onClose={() => setAdding(false)}
          onSaved={(c) => {
            qc.invalidateQueries({ queryKey: ["cameras"] });
            setAdding(false);
            nav(`/cameras/${c.id}`);
          }}
        />
      )}
    </div>
  );
}
