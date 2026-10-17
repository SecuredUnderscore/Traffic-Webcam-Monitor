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
        <span key={k} className={cx("chip", v === "ok" ? "tone-ok" : k === "note" || String(v).startsWith("off") ? "" : "tone-danger")} title={String(v)}>
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
    <div id={`event-${e.id}`} className={cx("card event-card", !e.acknowledged && "unread")} style={focus ? { outline: "2px solid var(--ring)" } : undefined}>
      <figure>
        <figcaption>Previous scan</figcaption>
        {e.prev_snapshot_id ? <img src={annotatedUrl(e.prev_snapshot_id, e.zone_id)} alt="Previous scan" loading="lazy" /> : <div className="snap-placeholder">No previous scan</div>}
      </figure>
      <figure>
        <figcaption>Triggering scan</figcaption>
        {e.snapshot_id ? <img src={annotatedUrl(e.snapshot_id, e.zone_id)} alt="Scan that triggered the alert" loading="lazy" /> : <div className="snap-placeholder">No image</div>}
      </figure>
      <div className="info">
        <div className="small muted">{fmtTime(e.ts)} · {timeAgo(e.ts, now)}</div>
        <h3>{e.title}</h3>
        <p className="small muted">{e.message}</p>
        <Delivery d={e.delivery} />
        <div className="spacer" />
        <div className="row">
          <Link to={`/cameras/${e.camera_id}`} className="btn sm">Open camera</Link>
          <span className="spacer" />
          {!e.acknowledged && (
            <button className="btn sm" onClick={async () => { await api.ack(e.id); refresh(); }}><Check size={14} /> Mark seen</button>
          )}
          <button className="btn sm icon ghost" title="Delete" onClick={async () => { await api.deleteEvent(e.id); refresh(); }}><Trash2 size={14} /></button>
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
          {!!events.data?.length && <div className="sub">{events.data.length} alert{events.data.length === 1 ? "" : "s"}</div>}
        </div>
        <select className="select" style={{ width: 220 }} value={cameraId ?? ""} onChange={(e) => setCameraId(e.target.value ? Number(e.target.value) : undefined)}>
          <option value="">All cameras</option>
          {cams.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <button className="btn" onClick={async () => { await api.ackAll(); qc.invalidateQueries({ queryKey: ["events"] }); qc.invalidateQueries({ queryKey: ["unread"] }); }}>
          <CheckCheck size={16} /> Mark all seen
        </button>
      </div>
      {events.isLoading && <Spinner />}
      {events.data?.length === 0 && (
        <div className="card empty-state">
          <BellOff size={20} />
          <h2>No alerts yet</h2>
          <p>Alerts appear here when a zone rule triggers, and are also sent to Discord or Pushover if enabled.</p>
        </div>
      )}
      <div className="col" style={{ gap: 16 }}>
        {events.data?.map((e) => <EventCard key={e.id} e={e} focus={focus === e.id} now={now} />)}
      </div>
    </div>
  );
}
