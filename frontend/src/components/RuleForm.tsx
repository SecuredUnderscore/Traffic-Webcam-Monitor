import { useState } from "react";
import type { RuleInput } from "../api";
import type { Rule, RuleKind, Zone } from "../types";
import { cx, DENSITY_LABEL, DENSITY_LEVELS, MOTION_LABEL, MOTION_STATES } from "../util";
import { Field, Modal, Spinner } from "./ui";

interface Preset {
  key: string;
  title: string;
  desc: string;
  rule: RuleInput;
}

const base = { cooldown_min: 30, enabled: true, channels: ["discord", "pushover"] };

export const PRESETS: Preset[] = [
  {
    key: "returns",
    title: "Traffic returns",
    desc: "Empty for a while, then vehicles appear. Closure lifted / road reopened.",
    rule: { ...base, name: "Traffic returns", kind: "density_change", params: { from: ["empty"], to: ["light", "moderate", "heavy"], min_prior: 2, confirm: 1 } },
  },
  {
    key: "starts",
    title: "Starts moving",
    desc: "Stopped traffic is moving again. Incident cleared.",
    rule: { ...base, name: "Starts moving", kind: "motion_change", params: { from: ["stopped"], to: ["moving", "slow"], min_prior: 1, confirm: 1 } },
  },
  {
    key: "stops",
    title: "Becomes stopped",
    desc: "Moving traffic comes to a standstill for 2 scans. Possible new incident.",
    rule: { ...base, name: "Traffic stopped", kind: "motion_change", params: { from: ["moving", "slow"], to: ["stopped"], min_prior: 1, confirm: 2 } },
  },
  {
    key: "empties",
    title: "Goes empty",
    desc: "A busy direction suddenly has no vehicles. Possible closure.",
    rule: { ...base, name: "Direction went empty", kind: "density_change", params: { from: ["moderate", "heavy"], to: ["empty"], min_prior: 2, confirm: 2 } },
  },
  {
    key: "heavy",
    title: "Heavy traffic",
    desc: "Vehicle count rises above a threshold.",
    rule: { ...base, name: "Heavy traffic", kind: "count_threshold", params: { op: "above", value: 10, scans: 2 } },
  },
];

const KIND_LABEL: Record<RuleKind, string> = {
  density_change: "Traffic level changes",
  motion_change: "Traffic flow changes",
  count_threshold: "Vehicle count threshold",
  activity_threshold: "Activity % threshold",
};

function StatePicker({ options, labels, value, onChange, prefix }: {
  options: string[]; labels: Record<string, string>; value: string[]; onChange: (v: string[]) => void; prefix: "d" | "m";
}) {
  return (
    <div className="state-picker">
      {options.map((o) => (
        <button
          key={o}
          type="button"
          className={cx("chip", `${prefix}-${o}`, value.includes(o) && "on")}
          onClick={() => onChange(value.includes(o) ? value.filter((x) => x !== o) : [...value, o])}
        >
          {labels[o]}
        </button>
      ))}
    </div>
  );
}

export function describeRule(r: Pick<Rule, "kind" | "params">): string {
  const p = r.params;
  if (r.kind === "density_change" || r.kind === "motion_change") {
    const L = r.kind === "density_change" ? DENSITY_LABEL : MOTION_LABEL;
    const from = (p.from ?? []).map((x: string) => L[x]).join("/");
    const to = (p.to ?? []).map((x: string) => L[x]).join("/");
    const conf = (p.confirm ?? 1) > 1 ? ` (confirmed over ${p.confirm} scans)` : "";
    return `${from} for ≥${p.min_prior ?? 1} scan${(p.min_prior ?? 1) > 1 ? "s" : ""} → ${to}${conf}`;
  }
  const unit = r.kind === "count_threshold" ? " vehicles" : "% activity";
  return `${p.op === "below" ? "Below" : "Above"} ${p.value}${unit} for ${p.scans} scan${p.scans > 1 ? "s" : ""}`;
}

export default function RuleForm({
  zone,
  rule,
  onClose,
  onSave,
}: {
  zone: Zone;
  rule?: Rule | null;
  onClose: () => void;
  onSave: (r: RuleInput) => Promise<void>;
}) {
  const [preset, setPreset] = useState<string | null>(rule ? null : "returns");
  const [v, setV] = useState<RuleInput>(
    rule ? { name: rule.name, kind: rule.kind, params: { ...rule.params }, cooldown_min: rule.cooldown_min, enabled: rule.enabled, channels: rule.channels } : structuredClone(PRESETS[0].rule),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const setP = (k: string, val: any) => setV((x) => ({ ...x, params: { ...x.params, [k]: val } }));
  const pick = (p: Preset) => {
    setPreset(p.key);
    setV(structuredClone(p.rule));
  };
  const setKind = (kind: RuleKind) => {
    setPreset(null);
    const params =
      kind === "density_change" ? { from: ["empty"], to: ["light", "moderate", "heavy"], min_prior: 2, confirm: 1 }
      : kind === "motion_change" ? { from: ["stopped"], to: ["moving"], min_prior: 1, confirm: 1 }
      : kind === "count_threshold" ? { op: "above", value: 10, scans: 1 }
      : { op: "above", value: 10, scans: 1 };
    setV((x) => ({ ...x, kind, params }));
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSave(v);
    } catch (e: any) {
      setError(e.message);
      setSaving(false);
    }
  };

  const isTransition = v.kind === "density_change" || v.kind === "motion_change";
  const p = v.params;
  const usesActivity = zone.metric === "activity";

  return (
    <Modal
      title={`${rule ? "Edit" : "New"} alert rule · ${zone.name}`}
      onClose={onClose}
      footer={
        <>
          {error && <span className="error-text" style={{ marginRight: "auto" }}>{error}</span>}
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={save} disabled={saving}>
            {saving && <Spinner size={14} />} Save rule
          </button>
        </>
      }
    >
      {!rule && (
        <div className="col">
          <div className="label">Start from a preset</div>
          <div className="preset-grid">
            {PRESETS.map((pr) => (
              <button key={pr.key} className={cx("preset", preset === pr.key && "on")} onClick={() => pick(pr)}>
                <div className="t">{pr.title}</div>
                <div className="d">{pr.desc}</div>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="form-grid">
        <Field label="Rule name">
          <input className="input" value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />
        </Field>
        <Field label="Type">
          <select className="select" value={v.kind} onChange={(e) => setKind(e.target.value as RuleKind)}>
            {(Object.keys(KIND_LABEL) as RuleKind[]).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
          </select>
        </Field>
      </div>

      {isTransition ? (
        <div className="card card-pad col" style={{ gap: 16, background: "var(--bg-2)" }}>
          <div className="field">
            <label>When the zone was…</label>
            <StatePicker
              prefix={v.kind === "density_change" ? "d" : "m"}
              options={v.kind === "density_change" ? DENSITY_LEVELS : MOTION_STATES}
              labels={v.kind === "density_change" ? DENSITY_LABEL : MOTION_LABEL}
              value={p.from ?? []}
              onChange={(x) => setP("from", x)}
            />
          </div>
          <div className="row" style={{ gap: 8 }}>
            <span className="label">for at least</span>
            <input className="input sm" type="number" min={1} max={50} style={{ width: 70 }} value={p.min_prior ?? 1} onChange={(e) => setP("min_prior", Number(e.target.value))} />
            <span className="label">consecutive scans,</span>
          </div>
          <div className="field">
            <label>…and then becomes</label>
            <StatePicker
              prefix={v.kind === "density_change" ? "d" : "m"}
              options={v.kind === "density_change" ? DENSITY_LEVELS : MOTION_STATES}
              labels={v.kind === "density_change" ? DENSITY_LABEL : MOTION_LABEL}
              value={p.to ?? []}
              onChange={(x) => setP("to", x)}
            />
          </div>
          <div className="row" style={{ gap: 8 }}>
            <span className="label">and stays that way for</span>
            <input className="input sm" type="number" min={1} max={20} style={{ width: 70 }} value={p.confirm ?? 1} onChange={(e) => setP("confirm", Number(e.target.value))} />
            <span className="label">scan(s) before alerting.</span>
          </div>
          <div className="hint">
            {v.kind === "density_change"
              ? `Levels come from this zone's ${usesActivity ? "activity %" : "vehicle count"} thresholds (${zone.thresholds.empty ?? (usesActivity ? 1.5 : 0)} / ${zone.thresholds.light ?? (usesActivity ? 6 : 3)} / ${zone.thresholds.moderate ?? (usesActivity ? 15 : 8)}).`
              : "Flow compares each scan with the previous one: vehicles still in the same spot, looking the same, minutes later = stopped."}
            {" "}Scans where the state can't be determined are skipped.
          </div>
        </div>
      ) : (
        <div className="card card-pad row wrap" style={{ gap: 8, background: "var(--bg-2)" }}>
          <span className="label">When {v.kind === "count_threshold" ? "the vehicle count" : "activity %"} is</span>
          <select className="select sm" style={{ width: 100 }} value={p.op} onChange={(e) => setP("op", e.target.value)}>
            <option value="above">above</option>
            <option value="below">below</option>
          </select>
          <input className="input sm" type="number" style={{ width: 80 }} value={p.value} onChange={(e) => setP("value", Number(e.target.value))} />
          <span className="label">for</span>
          <input className="input sm" type="number" min={1} style={{ width: 70 }} value={p.scans} onChange={(e) => setP("scans", Number(e.target.value))} />
          <span className="label">consecutive scans</span>
          <div className="hint" style={{ width: "100%" }}>Alerts once when the condition starts holding, not on every scan.</div>
        </div>
      )}

      <div className="form-grid">
        <Field label="Cooldown" hint="Minimum time between alerts from this rule.">
          <select className="select" value={v.cooldown_min} onChange={(e) => setV({ ...v, cooldown_min: Number(e.target.value) })}>
            {[0, 10, 15, 30, 60, 120, 240].map((m) => <option key={m} value={m}>{m === 0 ? "None" : m < 60 ? `${m} minutes` : `${m / 60} hour${m > 60 ? "s" : ""}`}</option>)}
          </select>
        </Field>
        <div className="field">
          <label>Send to</label>
          <div className="row" style={{ gap: 16, height: 34 }}>
            {["discord", "pushover"].map((ch) => (
              <label className="check" key={ch}>
                <input
                  type="checkbox"
                  checked={v.channels.includes(ch)}
                  onChange={(e) => setV({ ...v, channels: e.target.checked ? [...v.channels, ch] : v.channels.filter((c) => c !== ch) })}
                />
                {ch === "discord" ? "Discord" : "Pushover"}
              </label>
            ))}
          </div>
        </div>
      </div>
    </Modal>
  );
}
