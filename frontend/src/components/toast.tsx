import { CircleAlert, CircleCheck, Info, X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { classNames } from "../lib/format";

type ToastTone = "success" | "danger" | "info";

interface ToastInput {
  title: string;
  description?: string;
  tone?: ToastTone;
}

interface ToastItem extends ToastInput {
  id: number;
  leaving: boolean;
}

const ToastContext = createContext<((toast: ToastInput) => void) | null>(null);

const ICON: Record<ToastTone, ReactNode> = {
  success: <CircleCheck className="size-4 text-success-fg" aria-hidden />,
  danger: <CircleAlert className="size-4 text-danger-fg" aria-hidden />,
  info: <Info className="size-4 text-accent-fg" aria-hidden />,
};

const LIFETIME_MS: Record<ToastTone, number> = { success: 4000, info: 4500, danger: 7000 };

/** Short confirmations in the corner of the screen ("Copied", "Document deleted"). */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Map<number, number>());

  const dismiss = useCallback((id: number) => {
    window.clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setToasts((current) => current.map((toast) => (toast.id === id ? { ...toast, leaving: true } : toast)));
    window.setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), 160);
  }, []);

  const schedule = useCallback(
    (id: number, tone: ToastTone) => {
      window.clearTimeout(timers.current.get(id));
      timers.current.set(
        id,
        window.setTimeout(() => dismiss(id), LIFETIME_MS[tone]),
      );
    },
    [dismiss],
  );

  const push = useCallback(
    (toast: ToastInput) => {
      const id = nextId.current++;
      setToasts((current) => [...current.slice(-3), { ...toast, id, leaving: false }]);
      schedule(id, toast.tone ?? "success");
    },
    [schedule],
  );

  useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach((timer) => window.clearTimeout(timer));
  }, []);

  const region = (
    <div
      role="region"
      aria-label="Notifications"
      className="pointer-events-none fixed right-4 bottom-11 z-[90] flex w-[min(22rem,calc(100vw-2rem))] flex-col gap-2"
    >
      {toasts.map((toast) => {
        const tone = toast.tone ?? "success";
        return (
          <div
            key={toast.id}
            role={tone === "danger" ? "alert" : "status"}
            onMouseEnter={() => window.clearTimeout(timers.current.get(toast.id))}
            onMouseLeave={() => !toast.leaving && schedule(toast.id, tone)}
            className={classNames(
              "pointer-events-auto flex items-start gap-2.5 rounded-xl border border-line bg-raised py-2.5 pr-2 pl-3 shadow-lg transition-opacity duration-150",
              toast.leaving ? "opacity-0" : "animate-toast",
            )}
          >
            <span className="mt-0.5 shrink-0">{ICON[tone]}</span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-fg">{toast.title}</p>
              {toast.description && <p className="mt-0.5 text-sm text-fg-muted">{toast.description}</p>}
            </div>
            <button
              type="button"
              aria-label="Dismiss notification"
              onClick={() => dismiss(toast.id)}
              className="inline-flex size-6 shrink-0 items-center justify-center rounded-sm text-fg-subtle transition-colors duration-150 hover:bg-wash hover:text-fg"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          </div>
        );
      })}
    </div>
  );

  const value = useMemo(() => push, [push]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      {createPortal(region, document.body)}
    </ToastContext.Provider>
  );
}

export function useToast(): (toast: ToastInput) => void {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToast must be used inside <ToastProvider>");
  return value;
}
