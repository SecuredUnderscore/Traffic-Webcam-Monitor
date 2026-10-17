import { useCallback, useEffect, useRef, useState } from "react";
import type { Detection, Point } from "../types";
import SnapshotView, { pointsAttr, useRenderScale, type OverlayZone, type ZoneState } from "./SnapshotView";
import { cx, DRAW_COLOR } from "../util";

export type Tool = "select" | "rect" | "poly";

type Drag =
  | { kind: "vertex"; zoneId: number; index: number }
  | { kind: "move"; zoneId: number; start: Point; orig: Point[] }
  | { kind: "rect"; start: Point; cur: Point };

const clamp = (v: number) => Math.min(1, Math.max(0, v));

export default function ZoneEditor({
  src,
  width,
  height,
  zones,
  results,
  detections,
  showDetections,
  selectedId,
  tool,
  onSelect,
  onChange,
  onCreate,
  onToolDone,
}: {
  src: string | null;
  width: number;
  height: number;
  zones: OverlayZone[];
  results?: Record<number, ZoneState>;
  detections?: Detection[];
  showDetections: boolean;
  selectedId: number | null;
  tool: Tool;
  onSelect: (id: number | null) => void;
  /** Called once a drag finishes with the zone's new polygon. */
  onChange: (id: number, polygon: Point[]) => void;
  onCreate: (polygon: Point[]) => void;
  onToolDone: () => void;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const scale = useRenderScale(wrapRef, width);
  const px = (n: number) => n / Math.max(scale, 0.01);

  const [drag, setDrag] = useState<Drag | null>(null);
  const [live, setLive] = useState<Record<number, Point[]>>({});
  const [draft, setDraft] = useState<Point[]>([]);
  const [cursor, setCursor] = useState<Point | null>(null);

  const toNorm = useCallback(
    (e: { clientX: number; clientY: number }): Point => {
      const svg = svgRef.current!;
      const pt = svg.createSVGPoint();
      pt.x = e.clientX;
      pt.y = e.clientY;
      const p = pt.matrixTransform(svg.getScreenCTM()!.inverse());
      return [clamp(p.x / width), clamp(p.y / height)];
    },
    [width, height],
  );

  const capture = (e: React.PointerEvent) => {
    try {
      svgRef.current?.setPointerCapture(e.pointerId);
    } catch {
      /* pointer already released (e.g. very quick taps); dragging still works without capture */
    }
  };

  const polyOf = (z: OverlayZone) => live[z.id] ?? z.polygon;

  const finishDraft = useCallback(() => {
    if (draft.length >= 3) onCreate(draft);
    setDraft([]);
    onToolDone();
  }, [draft, onCreate, onToolDone]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (tool !== "poly" || (e.target as HTMLElement)?.tagName === "INPUT") return;
      if (e.key === "Enter") finishDraft();
      if (e.key === "Escape") {
        setDraft([]);
        onToolDone();
      }
      if (e.key === "Backspace") setDraft((d) => d.slice(0, -1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tool, finishDraft, onToolDone]);

  useEffect(() => setDraft([]), [tool]);

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    const p = toNorm(e);
    if (tool === "rect") {
      capture(e);
      setDrag({ kind: "rect", start: p, cur: p });
    } else if (tool === "poly") {
      if (draft.length >= 3) {
        const [fx, fy] = draft[0];
        const dist = Math.hypot((fx - p[0]) * width * scale, (fy - p[1]) * height * scale);
        if (dist < 12) return finishDraft();
      }
      setDraft((d) => [...d, p]);
    } else if (e.target === svgRef.current) {
      onSelect(null);
    }
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const p = toNorm(e);
    if (tool === "poly") setCursor(p);
    if (!drag) return;
    if (drag.kind === "rect") setDrag({ ...drag, cur: p });
    else if (drag.kind === "vertex") {
      const z = zones.find((z) => z.id === drag.zoneId)!;
      const poly = [...polyOf(z)];
      poly[drag.index] = p;
      setLive((l) => ({ ...l, [z.id]: poly }));
    } else if (drag.kind === "move") {
      let dx = p[0] - drag.start[0];
      let dy = p[1] - drag.start[1];
      // Keep the whole zone inside the image.
      const xs = drag.orig.map((q) => q[0]);
      const ys = drag.orig.map((q) => q[1]);
      dx = Math.min(1 - Math.max(...xs), Math.max(-Math.min(...xs), dx));
      dy = Math.min(1 - Math.max(...ys), Math.max(-Math.min(...ys), dy));
      setLive((l) => ({ ...l, [drag.zoneId]: drag.orig.map(([x, y]) => [x + dx, y + dy] as Point) }));
    }
  };

  const onPointerUp = () => {
    if (!drag) return;
    if (drag.kind === "rect") {
      const [x1, y1] = drag.start;
      const [x2, y2] = drag.cur;
      if (Math.abs(x2 - x1) * width * scale > 8 && Math.abs(y2 - y1) * height * scale > 8) {
        const [l, r, t, b] = [Math.min(x1, x2), Math.max(x1, x2), Math.min(y1, y2), Math.max(y1, y2)];
        onCreate([[l, t], [r, t], [r, b], [l, b]]);
      }
      onToolDone();
    } else if (live[drag.zoneId]) {
      onChange(drag.zoneId, live[drag.zoneId]);
    }
    setDrag(null);
  };

  // Drop local overrides once the saved geometry comes back from the server.
  useEffect(() => {
    setLive((l) => {
      const next = { ...l };
      for (const z of zones) if (next[z.id] && JSON.stringify(next[z.id]) === JSON.stringify(z.polygon)) delete next[z.id];
      return next;
    });
  }, [zones]);

  const startVertex = (e: React.PointerEvent, z: OverlayZone, index: number) => {
    e.stopPropagation();
    capture(e);
    setDrag({ kind: "vertex", zoneId: z.id, index });
  };

  const startInsert = (e: React.PointerEvent, z: OverlayZone, index: number) => {
    e.stopPropagation();
    const poly = [...polyOf(z)];
    poly.splice(index + 1, 0, toNorm(e));
    setLive((l) => ({ ...l, [z.id]: poly }));
    capture(e);
    setDrag({ kind: "vertex", zoneId: z.id, index: index + 1 });
  };

  const removeVertex = (z: OverlayZone, index: number) => {
    const poly = polyOf(z);
    if (poly.length <= 3) return;
    onChange(z.id, poly.filter((_, i) => i !== index));
  };

  const shown = zones.map((z) => ({ ...z, polygon: polyOf(z) }));
  const selected = shown.find((z) => z.id === selectedId);

  return (
    <div ref={wrapRef} className={cx("editor-wrap", tool !== "select" && "mode-draw")}>
      <SnapshotView
        src={src}
        width={width}
        height={height}
        zones={shown}
        results={results}
        detections={detections}
        showDetections={showDetections}
        highlight={selectedId}
        svgRef={svgRef}
        svgProps={{ onPointerDown, onPointerMove, onPointerUp, onPointerLeave: () => setCursor(null) }}
      >
        {tool === "select" &&
          shown.map((z) => (
            <polygon
              key={`hit${z.id}`}
              points={pointsAttr(z.polygon, width, height)}
              fill="transparent"
              style={{ cursor: z.id === selectedId ? "move" : "pointer" }}
              onPointerDown={(e) => {
                if (e.button !== 0) return;
                e.stopPropagation();
                onSelect(z.id);
                capture(e);
                setDrag({ kind: "move", zoneId: z.id, start: toNorm(e), orig: z.polygon });
              }}
            />
          ))}

        {tool === "select" && selected && (
          <g>
            {selected.polygon.map((p, i) => {
              const q = selected.polygon[(i + 1) % selected.polygon.length];
              return (
                <circle
                  key={`m${i}`}
                  cx={((p[0] + q[0]) / 2) * width}
                  cy={((p[1] + q[1]) / 2) * height}
                  r={px(4)}
                  fill={selected.color}
                  fillOpacity={0.55}
                  style={{ cursor: "copy" }}
                  onPointerDown={(e) => startInsert(e, selected, i)}
                >
                  <title>Drag to add a point</title>
                </circle>
              );
            })}
            {selected.polygon.map((p, i) => (
              <circle
                key={`v${i}`}
                cx={p[0] * width}
                cy={p[1] * height}
                r={px(6)}
                fill="#0d1117"
                stroke={selected.color}
                strokeWidth={px(2.5)}
                style={{ cursor: "grab" }}
                onPointerDown={(e) => startVertex(e, selected, i)}
                onDoubleClick={() => removeVertex(selected, i)}
              >
                <title>Drag to move · double-click to delete</title>
              </circle>
            ))}
          </g>
        )}

        {drag?.kind === "rect" && (
          <rect
            x={Math.min(drag.start[0], drag.cur[0]) * width}
            y={Math.min(drag.start[1], drag.cur[1]) * height}
            width={Math.abs(drag.cur[0] - drag.start[0]) * width}
            height={Math.abs(drag.cur[1] - drag.start[1]) * height}
            fill="rgba(88,166,255,0.15)"
            stroke={DRAW_COLOR}
            strokeWidth={px(2)}
            strokeDasharray={`${px(6)} ${px(4)}`}
          />
        )}

        {tool === "poly" && draft.length > 0 && (
          <g pointerEvents="none">
            <polyline
              points={pointsAttr(cursor ? [...draft, cursor] : draft, width, height)}
              fill="rgba(88,166,255,0.12)"
              stroke={DRAW_COLOR}
              strokeWidth={px(2)}
              strokeDasharray={`${px(6)} ${px(4)}`}
            />
            {draft.map((p, i) => (
              <circle
                key={i}
                cx={p[0] * width}
                cy={p[1] * height}
                r={px(i === 0 && draft.length >= 3 ? 8 : 4.5)}
                fill={i === 0 ? DRAW_COLOR : "#0d1117"}
                stroke={DRAW_COLOR}
                strokeWidth={px(2)}
              />
            ))}
          </g>
        )}
      </SnapshotView>
    </div>
  );
}
