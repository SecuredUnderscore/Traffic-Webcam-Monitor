import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { AlertTriangle, Clock, Loader2, Pause, Video, X } from "lucide-react";
import type { CameraStatus } from "../types";
import { cx, DENSITY_LABEL, MOTION_LABEL } from "../util";

export function Modal({
  title,
  onClose,
  children,
  footer,
  wide,
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={cx("modal", wide && "wide")} role="dialog" aria-modal="true">
        <div className="modal-head">
          <h2 className="grow">{title}</h2>
          <button className="btn ghost icon" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

type Toast = { id: number; text: string; kind: "info" | "ok" | "error" };
const ToastCtx = createContext<(text: string, kind?: Toast["kind"]) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, kind: Toast["kind"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 7000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className={cx("toast", t.kind)}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

export function Switch({ checked, onChange, title }: { checked: boolean; onChange: (v: boolean) => void; title?: string }) {
  return (
    <label className="switch" title={title}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span />
    </label>
  );
}

export function DensityChip({ value }: { value: string | null | undefined }) {
  if (!value) return null;
  return <span className={cx("chip", `d-${value}`)}>{DENSITY_LABEL[value] ?? value}</span>;
}

export function MotionChip({ value, hideNone }: { value: string | null | undefined; hideNone?: boolean }) {
  if (!value || (hideNone && (value === "none" || value === "unknown"))) return null;
  return <span className={cx("chip", `m-${value}`)}>{MOTION_LABEL[value] ?? value}</span>;
}

const STATUS_TEXT: Record<CameraStatus, string> = {
  ok: "Live",
  stale: "Not updating",
  error: "Fetch errors",
  paused: "Paused",
  pending: "Waiting for image",
};
const STATUS_TONE: Record<CameraStatus, string> = {
  ok: "tone-ok",
  stale: "tone-warn",
  error: "tone-danger",
  paused: "",
  pending: "tone-primary",
};

/** Camera status as a small text badge. */
export function StatusBadge({ status }: { status: CameraStatus }) {
  return <span className={cx("chip", STATUS_TONE[status])}>{STATUS_TEXT[status]}</span>;
}

/** Compact status for tight spots (sidebar): an icon only when something needs attention. */
export function StatusIcon({ status }: { status: CameraStatus }) {
  const Icon = status === "error" ? AlertTriangle : status === "stale" ? Clock : status === "paused" ? Pause : Video;
  const color = status === "error" ? "var(--danger)" : status === "stale" ? "var(--warn)" : "var(--text-muted)";
  return (
    <span className="status-icon row" title={STATUS_TEXT[status]}>
      <Icon size={14} color={color} aria-label={STATUS_TEXT[status]} />
    </span>
  );
}

export function Spinner({ size = 16 }: { size?: number }) {
  return <Loader2 size={size} className="spin" />;
}

export function Field({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

/** Re-render periodically so relative times ("3 min ago") stay fresh. */
export function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}
