import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { ImageOff } from "lucide-react";
import type { Detection, Point } from "../types";
import { DENSITY_LABEL } from "../util";

export interface OverlayZone {
  id: number;
  name: string;
  color: string;
  polygon: Point[];
}

export interface ZoneState {
  count: number;
  density: string;
  motion: string;
  detections?: number[];
}

/** Tracks rendered width so overlay strokes/handles keep a constant on-screen size. */
export function useRenderScale(ref: RefObject<Element | null>, naturalWidth: number) {
  const [scale, setScale] = useState(1);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setScale(el.clientWidth / Math.max(1, naturalWidth)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref, naturalWidth]);
  return scale;
}

export function zoneOfDetection(zones: OverlayZone[], results?: Record<number, ZoneState>) {
  const map = new Map<number, OverlayZone>();
  for (const z of zones) for (const i of results?.[z.id]?.detections ?? []) map.set(i, z);
  return map;
}

export function pointsAttr(poly: Point[], w: number, h: number) {
  return poly.map(([x, y]) => `${x * w},${y * h}`).join(" ");
}

export default function SnapshotView({
  src,
  width,
  height,
  zones = [],
  results,
  detections,
  showDetections = true,
  showLabels = true,
  highlight,
  svgRef,
  className,
  children,
  svgProps,
}: {
  src: string | null;
  width: number;
  height: number;
  zones?: OverlayZone[];
  results?: Record<number, ZoneState>;
  detections?: Detection[];
  showDetections?: boolean;
  showLabels?: boolean;
  highlight?: number | null;
  svgRef?: RefObject<SVGSVGElement | null>;
  className?: string;
  children?: ReactNode;
  svgProps?: React.SVGProps<SVGSVGElement>;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const scale = useRenderScale(wrap, width);
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  const px = (n: number) => n / Math.max(scale, 0.01);
  const byDet = zoneOfDetection(zones, results);

  if (!src || failed) {
    return (
      <div className="snap-placeholder">
        <div className="col" style={{ alignItems: "center" }}>
          <ImageOff size={28} />
          <span className="small">{failed ? "Image unavailable" : "No image yet"}</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`snap ${className ?? ""}`} ref={wrap}>
      <img src={src} width={width} height={height} alt="" draggable={false} onError={() => setFailed(true)} />
      <svg ref={svgRef} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" {...svgProps}>
        {zones.map((z) => (
          <polygon
            key={z.id}
            points={pointsAttr(z.polygon, width, height)}
            fill={z.color}
            fillOpacity={highlight === z.id ? 0.24 : 0.12}
            stroke={z.color}
            strokeWidth={px(highlight === z.id ? 3 : 2)}
            strokeLinejoin="round"
          />
        ))}
        {showDetections &&
          detections?.map((d, i) => {
            const z = byDet.get(i);
            return (
              <rect
                key={i}
                x={d.x1}
                y={d.y1}
                width={d.x2 - d.x1}
                height={d.y2 - d.y1}
                fill="none"
                stroke={z ? z.color : "#cbd5e1"}
                strokeOpacity={z ? 1 : 0.55}
                strokeWidth={px(z ? 1.6 : 1)}
                rx={px(1.5)}
              >
                <title>
                  {d.label} {(d.score * 100).toFixed(0)}%
                </title>
              </rect>
            );
          })}
        {showLabels &&
          zones.map((z) => {
            if (z.polygon.length < 3) return null;
            const top = z.polygon.reduce((a, b) => (b[1] < a[1] ? b : a));
            const r = results?.[z.id];
            const text = r ? `${z.name} · ${r.count} · ${DENSITY_LABEL[r.density] ?? r.density}` : z.name;
            return (
              <text
                key={`l${z.id}`}
                className="zone-label"
                x={top[0] * width}
                y={Math.max(px(16), top[1] * height - px(6))}
                fontSize={px(13)}
                strokeWidth={px(3)}
              >
                {text}
              </text>
            );
          })}
        {children}
      </svg>
    </div>
  );
}
