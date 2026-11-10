import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";

/** True while the media query matches; updates when the viewport or the OS setting changes. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);
  return matches;
}

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

export function prefersReducedMotion(): boolean {
  return window.matchMedia(REDUCED_MOTION).matches;
}

/** Smooth scrolling, unless the visitor has asked for reduced motion. */
export function scrollBehavior(): ScrollBehavior {
  return prefersReducedMotion() ? "auto" : "smooth";
}

/**
 * Counts from the previous value to `target` over `duration` ms (ease-out). With reduced motion,
 * or when the number has not changed, the target is shown at once.
 */
export function useCountUp(target: number, duration = 700): number {
  const [value, setValue] = useState(() => (prefersReducedMotion() ? target : 0));
  const from = useRef(prefersReducedMotion() ? target : 0);

  useEffect(() => {
    const start = from.current;
    if (start === target || prefersReducedMotion()) {
      from.current = target;
      setValue(target);
      return;
    }
    let frame = 0;
    const began = performance.now();
    const tick = (now: number) => {
      const progress = Math.min(1, (now - began) / duration);
      const eased = 1 - (1 - progress) ** 3;
      const current = start + (target - start) * eased;
      from.current = current;
      setValue(current);
      if (progress < 1) frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [target, duration]);

  return value;
}

/** State that survives a reload. Falls back to memory when storage is unavailable. */
export function usePersistentState<T>(key: string, initial: T, validate: (value: unknown) => value is T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = window.localStorage.getItem(key);
      if (stored != null) {
        const parsed: unknown = JSON.parse(stored);
        if (validate(parsed)) return parsed;
      }
    } catch {
      // ignore: unreadable or blocked storage
    }
    return initial;
  });
  const update = useCallback(
    (next: T) => {
      setValue(next);
      try {
        window.localStorage.setItem(key, JSON.stringify(next));
      } catch {
        // ignore
      }
    },
    [key],
  );
  return [value, update];
}

/** Calls `handler` for a keyboard shortcut such as "mod+k" ("mod" is Ctrl, or Cmd on a Mac). */
export function useHotkey(combo: string, handler: (event: KeyboardEvent) => void): void {
  const latest = useRef(handler);
  latest.current = handler;
  useEffect(() => {
    const parts = combo.toLowerCase().split("+");
    const key = parts[parts.length - 1];
    const needsMod = parts.includes("mod");
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== key) return;
      if (needsMod !== (event.ctrlKey || event.metaKey)) return;
      if (event.altKey) return;
      latest.current(event);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [combo]);
}

export const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform ?? "");

/** "Ctrl K" or "⌘K", for keyboard hints. */
export function modKeyLabel(key: string): string {
  return IS_MAC ? `⌘${key}` : `Ctrl ${key}`;
}

/**
 * Position and width of the active item inside a tab list or segmented control, for a
 * sliding indicator. Re-measured when the active key, the container size or the font changes.
 */
export function useActiveIndicator(container: RefObject<HTMLElement | null>, activeKey: string | number | null) {
  const [rect, setRect] = useState<{ left: number; width: number } | null>(null);

  useLayoutEffect(() => {
    const element = container.current;
    if (!element) return;
    const measure = () => {
      const active = element.querySelector<HTMLElement>("[data-active='true']");
      setRect(active ? { left: active.offsetLeft, width: active.offsetWidth } : null);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    void document.fonts?.ready.then(measure);
    return () => observer.disconnect();
  }, [container, activeKey]);

  return rect;
}

/** Keeps an element mounted for `exitMs` after `open` turns false, so that it can animate out. */
export function usePresence(open: boolean, exitMs = 180): { mounted: boolean; closing: boolean } {
  const [mounted, setMounted] = useState(open);
  useEffect(() => {
    if (open) {
      setMounted(true);
      return;
    }
    if (prefersReducedMotion()) {
      setMounted(false);
      return;
    }
    const timer = window.setTimeout(() => setMounted(false), exitMs);
    return () => window.clearTimeout(timer);
  }, [open, exitMs]);
  return { mounted: open || mounted, closing: !open && mounted };
}
