import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCheck, Trash2, BellOff } from "lucide-react";
import { annotatedUrl, api } from "../api";
import type { TrafficEvent } from "../types";
import { Spinner, useNow } from "../components/ui";
import { cx, fmtTime, timeAgo } from "../util";

function Delivery({ d }: { d: Record<string, any> }) {
  const entries = Object.entries(d).filter(([k]) => k !== "pending");
  if (d.pending && !entries.length) return <span className="chip">sending…</span>;
  if (!entries.length) return null;
  return (
    <div className="row wrap">
      {entries.map(([k, v]) => (
        <span key={k} className={cx("chip", v === "ok" ? "m-moving" : k === "note" || String(v).startsWith("off") ? "" : "m-stopped")} title={String(v)}>
          {k === "note" ? String(v) : `${k}: ${v === "ok" ? "sent" : String(v).startsWith("off") ? "off" : "failed"}`}
        </span>
      ))}
    </div>
  );
}

function EventCard({ e, focus, now }: { e: TrafficEvent; focus: boolean; now: number }) {
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["events"] });
    qc.invalidateQueries({ queryKey: ["unread"] });
  };
  return (
    <div id={`event-${e.id}`} className={cx("card event-card", !e.acknowledged && "unread")} style={focus ? { outline: "2px solid var(--accent)" } : undefined}>
      <div className="img-cell">
        {e.prev_snapshot_id ? <img src={annotatedUrl(e.prev_snapshot_id, e.zone_id)} alt="" loading="lazy" /> : <div className="snap-placeholder">No previous scan</div>}
        <div className="overlay-pill">Before</div>
      </div>
      <div className="img-cell">
        {e.snapshot_id ? <img src={annotatedUrl(e.snapshot_id, e.zone_id)} alt="" loading="lazy" /> : <div className="snap-placeholder">No image</div>}
        <div className="overlay-pill" style={{ color: "var(--accent)" }}>Now</div>
      </div>
      <div className="info">
        <div className="small muted">{fmtTime(e.ts)} · {timeAgo(e.ts, now)}</div>
        <div style={{ fontWeight: 600, fontSize: 15 }}>{e.title}</div>
        <div className="small" style={{ color: "var(--text-2)" }}>{e.message}</div>
        <Delivery d={e.delivery} />
        <div className="spacer" />
        <div className="row">
          <Link to={`/cameras/${e.camera_id}`} className="btn sm">Open camera</Link>
          <span className="spacer" />
          {!e.acknowledged && (
            <button className="btn sm" onClick={async () => { await api.ack(e.id); refresh(); }}><Check size={13} /> Mark seen</button>
          )}
          <button className="btn sm icon ghost" title="Delete" onClick={async () => { await api.deleteEvent(e.id); refresh(); }}><Trash2 size={13} /></button>
        </div>
      </div>
    </div>
  );
}

export default function EventsPage() {
  const [params] = useSearchParams();
  const focus = Number(params.get("event")) || null;
  const [cameraId, setCameraId] = useState<number | undefined>();
  const qc = useQueryClient();
  const now = useNow(30000);
  const cams = useQuery({ queryKey: ["cameras"], queryFn: api.cameras });
  const events = useQuery({ queryKey: ["events", cameraId], queryFn: () => api.events(cameraId, 200), refetchInterval: 15000 });

  useEffect(() => {
    if (focus && events.data) document.getElementById(`event-${focus}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focus, events.data]);

  return (
    <div className="page">
      <div className="page-head">
        <div className="grow">
          <h1>Alerts</h1>
          <div className="sub">Every rule trigger, with the scan before and the scan that triggered it.</div>
        </div>
        <select className="select" style={{ width: 220 }} value={cameraId ?? ""} onChange={(e) => setCameraId(e.target.value ? Number(e.target.value) : undefined)}>
          <option value="">All cameras</option>
          {cams.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <button className="btn" onClick={async () => { await api.ackAll(); qc.invalidateQueries({ queryKey: ["events"] }); qc.invalidateQueries({ queryKey: ["unread"] }); }}>
          <CheckCheck size={15} /> Mark all seen
        </button>
      </div>
      {events.isLoading && <Spinner />}
      {events.data?.length === 0 && (
        <div className="card empty-state">
          <div className="big-icon"><BellOff size={28} /></div>
          <h2>No alerts yet</h2>
          <p className="muted">When a zone's rule triggers, the alert shows up here and on Discord/Pushover.</p>
        </div>
      )}
      <div className="col" style={{ gap: 14 }}>
        {events.data?.map((e) => <EventCard key={e.id} e={e} focus={focus === e.id} now={now} />)}
      </div>
    </div>
  );
}
