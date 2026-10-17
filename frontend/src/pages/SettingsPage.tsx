import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Eye, EyeOff, HardDrive, MessageSquare, Save, ScanSearch, Send, Smartphone } from "lucide-react";
import { api } from "../api";
import type { Settings } from "../types";
import { Field, Spinner, Switch, useToast } from "../components/ui";

function Secret({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  const [show, setShow] = useState(false);
  return (
    <div className="row">
      <input className="input mono" type={show ? "text" : "password"} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} autoComplete="off" />
      <button className="btn icon ghost" onClick={() => setShow(!show)} title={show ? "Hide" : "Show"}>{show ? <EyeOff size={15} /> : <Eye size={15} />}</button>
    </div>
  );
}

function Section({ icon, title, right, children }: { icon: React.ReactNode; title: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="card">
      <div className="card-head">{icon}<h3 className="grow">{title}</h3>{right}</div>
      <div className="card-body col" style={{ gap: 16 }}>{children}</div>
    </div>
  );
}

export default function SettingsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  const [s, setS] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  useEffect(() => { if (q.data && !s) setS(q.data); }, [q.data, s]);
  if (!s) return <div className="page"><Spinner /></div>;
  const set = (k: string, v: any) => setS({ ...s, [k]: v });
  // Filling in credentials for the first time switches the channel on; that's what people expect.
  const setCred = (k: string, v: string, channel: "discord" | "pushover") => {
    const next = { ...s, [k]: v };
    const ready = channel === "discord" ? !!next.discord_webhook_url : !!(next.pushover_app_token && next.pushover_user_key);
    const wasReady = channel === "discord" ? !!s.discord_webhook_url : !!(s.pushover_app_token && s.pushover_user_key);
    if (ready && !wasReady) next[`${channel}_enabled`] = true;
    setS(next);
  };
  const offWarning = (channel: "discord" | "pushover") => {
    const ready = channel === "discord" ? !!s.discord_webhook_url : !!(s.pushover_app_token && s.pushover_user_key);
    return ready && !s[`${channel}_enabled`] ? (
      <div className="callout warn"><AlertTriangle size={16} /> Switched off: rule alerts won't be sent to {channel === "discord" ? "Discord" : "Pushover"}. Turn on the switch above and Save.</div>
    ) : null;
  };
  const enabledSwitch = (channel: "discord" | "pushover") => (
    <label className="check small">
      {s[`${channel}_enabled`] ? "On" : "Off"}
      <Switch checked={s[`${channel}_enabled`]} onChange={(v) => set(`${channel}_enabled`, v)} />
    </label>
  );
  const dirty = JSON.stringify(s) !== JSON.stringify(q.data);

  const save = async () => {
    setSaving(true);
    try {
      const saved = await api.saveSettings(s);
      qc.setQueryData(["settings"], saved);
      setS(saved);
      toast("Settings saved", "ok");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  const test = async (ch: "discord" | "pushover") => {
    setTesting(ch);
    try {
      const r = await api.testChannel(ch, s);
      toast(r.result === "ok" ? `Test sent to ${ch}` : `${ch}: ${r.result}`, r.result === "ok" ? "ok" : "error");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setTesting(null);
    }
  };

  return (
    <div className="page narrow">
      <div className="page-head">
        <div className="grow"><h1>Settings</h1></div>
        <button className="btn primary" onClick={save} disabled={!dirty || saving}>{saving ? <Spinner size={14} /> : <Save size={15} />} Save</button>
      </div>

      <div className="col" style={{ gap: 16 }}>
        <Section
          icon={<MessageSquare size={16} />}
          title="Discord"
          right={enabledSwitch("discord")}
        >
          {offWarning("discord")}
          <Field label="Webhook URL" hint="Discord channel → Edit Channel → Integrations → Webhooks → New Webhook → Copy URL. Alerts include the annotated image, plus the previous scan if enabled below.">
            <Secret value={s.discord_webhook_url} onChange={(v) => setCred("discord_webhook_url", v, "discord")} placeholder="https://discord.com/api/webhooks/…" />
          </Field>
          <div className="form-grid">
            <Field label="Bot name"><input className="input" value={s.discord_username} onChange={(e) => set("discord_username", e.target.value)} /></Field>
            <Field label="Mention (optional)" hint="e.g. <@&ROLE_ID>, <@USER_ID> or @here">
              <input className="input mono" value={s.discord_mention} onChange={(e) => set("discord_mention", e.target.value)} />
            </Field>
          </div>
          <div><button className="btn" onClick={() => test("discord")} disabled={!s.discord_webhook_url || testing === "discord"}>{testing === "discord" ? <Spinner size={14} /> : <Send size={14} />} Send test</button></div>
        </Section>

        <Section
          icon={<Smartphone size={16} />}
          title="Pushover"
          right={enabledSwitch("pushover")}
        >
          {offWarning("pushover")}
          <div className="form-grid">
            <Field label="Application API token" hint="Create an application at pushover.net/apps/build">
              <Secret value={s.pushover_app_token} onChange={(v) => setCred("pushover_app_token", v, "pushover")} />
            </Field>
            <Field label="User or group key" hint="Shown on your pushover.net dashboard">
              <Secret value={s.pushover_user_key} onChange={(v) => setCred("pushover_user_key", v, "pushover")} />
            </Field>
            <Field label="Priority">
              <select className="select" value={s.pushover_priority} onChange={(e) => set("pushover_priority", Number(e.target.value))}>
                <option value={-2}>Lowest (no notification)</option>
                <option value={-1}>Low (quiet)</option>
                <option value={0}>Normal</option>
                <option value={1}>High (bypass quiet hours)</option>
                <option value={2}>Emergency (repeat until acknowledged)</option>
              </select>
            </Field>
            <Field label="Sound (optional)" hint="e.g. pushover, siren, cosmic, none">
              <input className="input" value={s.pushover_sound} onChange={(e) => set("pushover_sound", e.target.value)} />
            </Field>
            <Field label="Device (optional)" hint="Limit to one device name">
              <input className="input" value={s.pushover_device} onChange={(e) => set("pushover_device", e.target.value)} />
            </Field>
          </div>
          <div className="hint">Pushover allows one image per message, so it gets a single side-by-side “before | now” picture.</div>
          <div><button className="btn" onClick={() => test("pushover")} disabled={!s.pushover_app_token || !s.pushover_user_key || testing === "pushover"}>{testing === "pushover" ? <Spinner size={14} /> : <Send size={14} />} Send test</button></div>
        </Section>

        <Section icon={<Send size={16} />} title="Alert content">
          <label className="check"><input type="checkbox" checked={s.send_before_image} onChange={(e) => set("send_before_image", e.target.checked)} /> Include the previous scan as a “before” image</label>
          <Field label="TrafficWatch address (optional)" hint="If set, alerts link back to the event, e.g. http://192.168.1.20:8080">
            <input className="input mono" value={s.app_base_url} placeholder="http://localhost:8080" onChange={(e) => set("app_base_url", e.target.value)} />
          </Field>
        </Section>

        <Section icon={<ScanSearch size={16} />} title="Vehicle detection (defaults)">
          <div className="form-grid">
            <Field label="Model" hint="Compare options in Detector Lab. 'n' = fastest, 'm' = most accurate.">
              <select className="select" value={s.detector_model} onChange={(e) => set("detector_model", e.target.value)}>
                {meta.data?.models.map((m) => <option key={m.id} value={m.id}>{m.id} ({m.size_mb} MB)</option>)}
              </select>
            </Field>
            <Field label="Tiling" hint="Extra passes over zoomed-in tiles find small, distant vehicles.">
              <select className="select" value={s.detector_tile_grid} onChange={(e) => set("detector_tile_grid", Number(e.target.value))}>
                <option value={0}>Off (full frame only)</option>
                <option value={2}>2×2 tiles (recommended)</option>
                <option value={3}>3×3 tiles</option>
              </select>
            </Field>
            <Field label="Hardware">
              <select className="select" value={s.detector_device} onChange={(e) => set("detector_device", e.target.value)}>
                {meta.data?.devices.map((d) => <option key={d} value={d}>{d === "cuda" ? "NVIDIA GPU (CUDA)" : "CPU"}</option>)}
              </select>
            </Field>
            <Field label={`Confidence threshold: ${Number(s.detector_conf).toFixed(2)}`} hint="Lower finds more vehicles but more false positives.">
              <input type="range" min={0.05} max={0.8} step={0.05} value={s.detector_conf} onChange={(e) => set("detector_conf", Number(e.target.value))} />
            </Field>
          </div>
        </Section>

        <Section icon={<HardDrive size={16} />} title="Storage">
          <div className="form-grid">
            <Field label="Keep scan images for" hint="Images attached to alerts are kept with the alert.">
              <select className="select" value={s.retention_hours} onChange={(e) => set("retention_hours", Number(e.target.value))}>
                {[12, 24, 48, 72, 168, 336].map((h) => <option key={h} value={h}>{h < 48 ? `${h} hours` : `${h / 24} days`}</option>)}
              </select>
            </Field>
            <Field label="Keep alerts for">
              <select className="select" value={s.event_retention_days} onChange={(e) => set("event_retention_days", Number(e.target.value))}>
                {[7, 14, 30, 90, 365].map((d) => <option key={d} value={d}>{d} days</option>)}
              </select>
            </Field>
          </div>
          <div>
            <button className="btn" onClick={async () => { const r = await api.cleanup(); toast(`Removed ${r.snapshots_deleted} old scans, ${r.events_deleted} old alerts`, "ok"); }}>Run cleanup now</button>
          </div>
        </Section>
      </div>
    </div>
  );
}
