import type { Observation } from "../types";
import { DENSITY_COLOR, fmtTime, MOTION_LABEL } from "../util";

const MOTION_COLOR: Record<string, string> = { stopped: "#ef4444", slow: "#f97316", moving: "#22c55e" };

/** Vehicle count (or activity) per scan; the strip underneath shows flow state. */
export default function ZoneChart({ data, metric }: { data: Observation[]; metric: "count" | "activity" }) {
  if (data.length < 2) return <div className="hint">History appears after a few scans.</div>;
  const W = 340, H = 80, PAD = 4, STRIP = 6;
  const vals = data.map((o) => (metric === "count" ? o.count : o.activity ?? 0));
  const max = Math.max(1, ...vals);
  const x = (i: number) => PAD + (i / (data.length - 1)) * (W - PAD * 2);
  const y = (v: number) => H - STRIP - 6 - (v / max) * (H - STRIP - 16);
  const line = vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const bw = (W - PAD * 2) / data.length;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="chart" preserveAspectRatio="none">
        <path d={`${line}L${x(data.length - 1)},${H - STRIP - 6}L${x(0)},${H - STRIP - 6}Z`} fill="rgba(56,189,248,0.12)" />
        <path d={line} fill="none" stroke="#38bdf8" strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
        {data.map((o, i) => (
          <g key={i}>
            <circle cx={x(i)} cy={y(vals[i])} r={2} fill={DENSITY_COLOR[o.density] ?? "#94a3b8"}>
              <title>{`${fmtTime(o.ts)} · ${metric === "count" ? `${o.count} vehicles` : `${(o.activity ?? 0).toFixed(1)}% activity`} · ${o.density} · ${MOTION_LABEL[o.motion]}`}</title>
            </circle>
            <rect x={PAD + i * bw} y={H - STRIP} width={Math.max(1, bw - 0.5)} height={STRIP} fill={MOTION_COLOR[o.motion] ?? "#1f2c44"} />
          </g>
        ))}
        <text x={W - PAD} y={11} textAnchor="end" fontSize={9} fill="#7d8aa3">max {metric === "count" ? max : `${max.toFixed(0)}%`}</text>
      </svg>
      <div className="row small muted" style={{ justifyContent: "space-between" }}>
        <span>{fmtTime(data[0].ts)}</span>
        <span className="row" style={{ gap: 10 }}>
          <span className="row" style={{ gap: 4 }}><span className="zone-swatch" style={{ background: "#22c55e" }} />moving</span>
          <span className="row" style={{ gap: 4 }}><span className="zone-swatch" style={{ background: "#f97316" }} />slow</span>
          <span className="row" style={{ gap: 4 }}><span className="zone-swatch" style={{ background: "#ef4444" }} />stopped</span>
        </span>
        <span>{fmtTime(data[data.length - 1].ts)}</span>
      </div>
    </div>
  );
}
