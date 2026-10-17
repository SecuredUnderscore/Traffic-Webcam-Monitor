import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bell, Camera as CameraIcon, Clock, Plus, RefreshCw } from "lucide-react";
import { api, snapshotUrl } from "../api";
import type { Camera } from "../types";
import SnapshotView from "../components/SnapshotView";
import CameraForm from "../components/CameraForm";
import { DensityChip, MotionChip, Spinner, StatusDot, useNow, useToast } from "../components/ui";
import { fmtInterval, timeAgo, timeUntil } from "../util";

function CameraCard({ cam, now }: { cam: Camera; now: number }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [checking, setChecking] = useState(false);
  const results = Object.fromEntries(cam.zones.filter((z) => z.latest).map((z) => [z.id, z.latest!]));
  const rules = cam.zones.reduce((n, z) => n + z.rules.filter((r) => r.enabled).length, 0);

  const check = async (e: React.MouseEvent) => {
    e.preventDefault();
    setChecking(true);
    try {
      const r = await api.checkNow(cam.id);
      toast(r.result.status === "new" ? "New image analyzed" : r.result.status === "unchanged" ? "No new image yet" : `Error: ${r.result.error}`,
        r.result.status === "error" ? "error" : "info");
      qc.invalidateQueries({ queryKey: ["cameras"] });
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="card cam-card">
      <Link to={`/cameras/${cam.id}`} className="cover">
        <SnapshotView
          src={cam.latest ? snapshotUrl(cam.latest.id, cam.latest.sha) : null}
          width={cam.latest?.width ?? 640}
          height={cam.latest?.height ?? 480}
          zones={cam.zones.filter((z) => z.enabled)}
          results={results}
          detections={cam.latest?.detections}
          showLabels={false}
        />
        <div className="overlay-pill">
          <StatusDot status={cam.status} />
          {cam.latest ? timeAgo(cam.latest.ts, now) : "no image"}
        </div>
        {cam.latest?.view_shift && (
          <div className="overlay-pill right" style={{ color: "#fde047" }}>
            <AlertTriangle size={13} /> View changed
          </div>
        )}
      </Link>
      <div className="meta">
        <div className="row">
          <Link to={`/cameras/${cam.id}`} className="cam-title grow ellipsis" style={{ color: "inherit" }}>{cam.name}</Link>
          <button className="btn sm icon ghost" title="Check now" onClick={check} disabled={checking}>
            {checking ? <Spinner size={14} /> : <RefreshCw size={14} />}
          </button>
        </div>
        {cam.zones.length === 0 ? (
          <div className="small muted">No zones yet. <Link to={`/cameras/${cam.id}`}>Draw zones</Link> to start detecting traffic changes.</div>
        ) : (
          <div className="col" style={{ gap: 6 }}>
            {cam.zones.filter((z) => z.enabled).map((z) => (
              <div key={z.id} className="zone-line">
                <span className="zone-swatch" style={{ background: z.color }} />
                <span className="ellipsis" style={{ maxWidth: 150, fontWeight: 500 }}>{z.name}</span>
                {z.latest ? (
                  <>
                    <span className="muted small mono">{z.metric === "count" ? `${z.latest.count} veh` : `${(z.latest.activity ?? 0).toFixed(1)}%`}</span>
                    <DensityChip value={z.latest.density} />
                    <MotionChip value={z.latest.motion} hideNone />
                  </>
                ) : (
                  <span className="muted small">waiting for scan</span>
                )}
              </div>
            ))}
          </div>
        )}
        <div className="row small muted" style={{ gap: 14 }}>
          <span className="row" style={{ gap: 4 }}><Clock size={12} /> every {fmtInterval(cam.interval_sec)}</span>
          {cam.enabled && <span>next {timeUntil(cam.next_check_at, now)}</span>}
          <span className="row" style={{ gap: 4 }}><Bell size={12} /> {rules} rule{rules === 1 ? "" : "s"}</span>
        </div>
        {cam.last_error && cam.status === "error" && (
          <div className="callout err small"><AlertTriangle size={14} /> {cam.last_error}</div>
        )}
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

  const live = cams.data?.filter((c) => c.status === "ok").length ?? 0;

  return (
    <div className="page">
      <div className="page-head">
        <div className="grow">
          <h1>Cameras</h1>
          {cams.data && cams.data.length > 0 && (
            <div className="sub">{live} of {cams.data.length} live · alerts fire when a zone's traffic changes between scans</div>
          )}
        </div>
        <button className="btn primary" onClick={() => setAdding(true)}><Plus size={16} /> Add camera</button>
      </div>

      {cams.isLoading && <Spinner />}
      {cams.data?.length === 0 && (
        <div className="card empty-state">
          <div className="big-icon"><CameraIcon size={30} /></div>
          <h2>Add your first traffic camera</h2>
          <p className="muted" style={{ maxWidth: 520, margin: "8px auto 20px" }}>
            Paste a link to a public traffic-camera still image. TrafficWatch checks it on your schedule, finds the vehicles,
            and alerts you on Discord or Pushover when traffic in a direction changes, e.g. a closed lane reopening or stopped traffic starting to move.
          </p>
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
