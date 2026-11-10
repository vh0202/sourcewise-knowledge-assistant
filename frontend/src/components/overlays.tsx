// Things that float above the page: tooltips, menus, dialogs and drawers.

import { X } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactElement,
  type ReactNode,
  type Ref,
} from "react";
import { createPortal } from "react-dom";

import { classNames } from "../lib/format";
import { usePresence } from "../lib/hooks";

// -- Positioning -------------------------------------------------------------------------------
export type Side = "top" | "bottom" | "left" | "right";
export type Align = "start" | "center" | "end";

const VIEWPORT_MARGIN = 8;

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), Math.max(min, max));
}

/** Where to put a floating box of `size` next to `anchor`, flipping sides when there is no room. */
function computePosition(anchor: DOMRect, size: { width: number; height: number }, side: Side, align: Align, gap: number) {
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  let placed = side;
  if (side === "top" && anchor.top - gap - size.height < VIEWPORT_MARGIN && viewportHeight - anchor.bottom > anchor.top) placed = "bottom";
  else if (side === "bottom" && anchor.bottom + gap + size.height > viewportHeight - VIEWPORT_MARGIN && anchor.top > viewportHeight - anchor.bottom) placed = "top";
  else if (side === "left" && anchor.left - gap - size.width < VIEWPORT_MARGIN) placed = "right";
  else if (side === "right" && anchor.right + gap + size.width > viewportWidth - VIEWPORT_MARGIN) placed = "left";

  let left: number;
  let top: number;
  if (placed === "top" || placed === "bottom") {
    top = placed === "top" ? anchor.top - gap - size.height : anchor.bottom + gap;
    left = align === "start" ? anchor.left : align === "end" ? anchor.right - size.width : anchor.left + anchor.width / 2 - size.width / 2;
  } else {
    left = placed === "left" ? anchor.left - gap - size.width : anchor.right + gap;
    top = align === "start" ? anchor.top : align === "end" ? anchor.bottom - size.height : anchor.top + anchor.height / 2 - size.height / 2;
  }
  return {
    left: Math.round(clamp(left, VIEWPORT_MARGIN, viewportWidth - size.width - VIEWPORT_MARGIN)),
    top: Math.round(clamp(top, VIEWPORT_MARGIN, viewportHeight - size.height - VIEWPORT_MARGIN)),
  };
}

interface FloatingProps {
  open: boolean;
  /** Returns the element to attach to (looked up lazily, when the box opens or the page moves). */
  anchor: () => Element | null | undefined;
  side?: Side;
  align?: Align;
  gap?: number;
  className?: string;
  children: ReactNode;
  ref?: Ref<HTMLDivElement>;
}

/**
 * A fixed-position box attached to an anchor element. It is rendered into <body>, or into the
 * enclosing modal <dialog> when there is one (anything outside a modal dialog is inert and
 * painted beneath it), so it is never clipped by a scrolling pane.
 */
export function Floating({ open, anchor, side = "top", align = "center", gap = 8, className, children, ref }: FloatingProps) {
  const box = useRef<HTMLDivElement | null>(null);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);

  useLayoutEffect(() => {
    if (!open) {
      setPosition(null);
      return;
    }
    const update = () => {
      const target = anchor();
      const element = box.current;
      if (!target || !element) return;
      setPosition(computePosition(target.getBoundingClientRect(), { width: element.offsetWidth, height: element.offsetHeight }, side, align, gap));
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
    // `anchor` is a fresh closure on every render; the position depends only on the values below.
  }, [open, side, align, gap]);

  if (!open) return null;
  const root = anchor()?.closest("dialog") ?? document.body;
  const style: CSSProperties = { position: "fixed", left: position?.left ?? 0, top: position?.top ?? 0, visibility: position ? "visible" : "hidden" };
  return createPortal(
    <div
      ref={(element) => {
        box.current = element;
        if (typeof ref === "function") ref(element);
        else if (ref) ref.current = element;
      }}
      style={style}
      className={classNames("z-[100]", className)}
    >
      {children}
    </div>,
    root,
  );
}

// -- Tooltip -----------------------------------------------------------------------------------
let lastTooltipClosedAt = 0;

interface TooltipProps {
  label: ReactNode;
  /** A keyboard hint shown after the label, e.g. "Ctrl K". */
  shortcut?: string;
  side?: Side;
  align?: Align;
  disabled?: boolean;
  children: ReactElement;
}

/**
 * A small label on hover or keyboard focus. It decorates its child without adding a box of its
 * own (the wrapper is `display: contents`), so layout is unaffected. The tooltip is visual only:
 * the child must still carry its own accessible name.
 */
export function Tooltip({ label, shortcut, side = "top", align = "center", disabled = false, children }: TooltipProps) {
  const wrapper = useRef<HTMLSpanElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const [open, setOpen] = useState(false);

  const hide = useCallback(() => {
    window.clearTimeout(timer.current);
    setOpen((current) => {
      if (current) lastTooltipClosedAt = performance.now();
      return false;
    });
  }, []);

  const show = (immediate: boolean) => {
    window.clearTimeout(timer.current);
    if (disabled) return;
    // Moving from one control to the next shows the next tooltip without the usual delay.
    const wait = immediate || performance.now() - lastTooltipClosedAt < 400 ? 0 : 450;
    timer.current = window.setTimeout(() => setOpen(true), wait);
  };

  useEffect(() => () => window.clearTimeout(timer.current), []);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => event.key === "Escape" && hide();
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("scroll", hide, true);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("scroll", hide, true);
    };
  }, [open, hide]);

  return (
    <span
      ref={wrapper}
      className="contents"
      onMouseEnter={() => show(false)}
      onMouseLeave={hide}
      onFocus={(event) => (event.target as HTMLElement).matches(":focus-visible") && show(true)}
      onBlur={hide}
      onPointerDown={hide}
    >
      {children}
      <Floating open={open} anchor={() => wrapper.current?.firstElementChild} side={side} align={align} gap={6} className="pointer-events-none">
        <span
          role="tooltip"
          className="flex max-w-64 animate-fade-in items-center gap-2 rounded-md bg-inverse px-2 py-1 text-xs font-medium text-fg-inverse shadow-md"
        >
          {label}
          {shortcut && <kbd className="rounded-xs bg-white/15 px-1 font-sans text-2xs text-fg-inverse">{shortcut}</kbd>}
        </span>
      </Floating>
    </span>
  );
}

// -- Menu --------------------------------------------------------------------------------------
interface MenuTriggerProps {
  ref: Ref<HTMLButtonElement>;
  onClick: () => void;
  "aria-haspopup": "menu";
  "aria-expanded": boolean;
  "aria-controls": string | undefined;
  "data-open": boolean;
}

const MenuContext = createContext<{ close: (returnFocus?: boolean) => void } | null>(null);

interface MenuProps {
  /** Accessible name of the menu. */
  label: string;
  /** Renders the button that opens the menu; spread the given props onto it. */
  trigger: (props: MenuTriggerProps) => ReactElement;
  side?: Side;
  align?: Align;
  children: ReactNode;
}

/** A dropdown menu: arrow keys move, Enter chooses, Escape or a click elsewhere closes. */
export function Menu({ label, trigger, side = "bottom", align = "end", children }: MenuProps) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const id = useId();

  const close = useCallback((returnFocus = true) => {
    setOpen(false);
    if (returnFocus) button.current?.focus();
  }, []);

  const items = () => Array.from(list.current?.querySelectorAll<HTMLElement>("[role='menuitem']:not([disabled])") ?? []);

  useEffect(() => {
    if (!open) return;
    // Focus the first item once the menu has been positioned.
    const frame = window.requestAnimationFrame(() => items()[0]?.focus());
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!list.current?.contains(target) && !button.current?.contains(target)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("pointerdown", onPointerDown, true);
    };
  }, [open]);

  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const all = items();
    const index = all.indexOf(document.activeElement as HTMLElement);
    const focus = (next: number) => {
      event.preventDefault();
      all[(next + all.length) % all.length]?.focus();
    };
    if (event.key === "ArrowDown") focus(index + 1);
    else if (event.key === "ArrowUp") focus(index - 1);
    else if (event.key === "Home") focus(0);
    else if (event.key === "End") focus(all.length - 1);
    else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
    } else if (event.key === "Tab") setOpen(false);
  };

  return (
    <MenuContext.Provider value={{ close }}>
      {trigger({
        ref: button,
        onClick: () => setOpen((current) => !current),
        "aria-haspopup": "menu",
        "aria-expanded": open,
        "aria-controls": open ? id : undefined,
        "data-open": open,
      })}
      <Floating open={open} anchor={() => button.current} side={side} align={align} gap={4}>
        <div
          ref={list}
          id={id}
          role="menu"
          aria-label={label}
          onKeyDown={onKeyDown}
          className="min-w-44 origin-top animate-pop rounded-lg border border-line bg-raised p-1 shadow-lg"
        >
          {children}
        </div>
      </Floating>
    </MenuContext.Provider>
  );
}

interface MenuItemProps {
  icon?: ReactNode;
  danger?: boolean;
  disabled?: boolean;
  onSelect: () => void;
  children: ReactNode;
}

export function MenuItem({ icon, danger = false, disabled = false, onSelect, children }: MenuItemProps) {
  const menu = useContext(MenuContext);
  return (
    <button
      type="button"
      role="menuitem"
      tabIndex={-1}
      disabled={disabled}
      onClick={() => {
        menu?.close(false);
        onSelect();
      }}
      className={classNames(
        "flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-sm transition-colors duration-150 focus:outline-none disabled:opacity-50",
        danger
          ? "text-danger-fg hover:bg-danger-soft focus-visible:bg-danger-soft"
          : "text-fg hover:bg-wash focus-visible:bg-wash",
      )}
    >
      {icon && <span className={classNames("flex size-4 shrink-0 items-center justify-center", !danger && "text-fg-subtle")}>{icon}</span>}
      <span className="min-w-0 flex-1 truncate">{children}</span>
    </button>
  );
}

// -- Modal dialog ------------------------------------------------------------------------------
interface ModalProps {
  title: string;
  description?: ReactNode;
  onClose: () => void;
  children?: ReactNode;
  footer: ReactNode;
}

/** A modal dialog built on the native <dialog> element (focus trapping and Esc come for free). */
export function Modal({ title, description, onClose, children, footer }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
    return () => dialog?.close();
  }, []);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === ref.current) onClose(); // a click on the backdrop
      }}
      className="m-auto w-[min(92vw,27rem)] animate-pop overflow-hidden rounded-2xl border border-line bg-raised p-0 shadow-xl"
    >
      <div className="flex items-start justify-between gap-4 px-5 pt-5">
        <div className="min-w-0">
          <h2 id={titleId} className="text-lg font-semibold tracking-tight text-fg">
            {title}
          </h2>
          {description && <p className="mt-1.5 text-base text-fg-muted">{description}</p>}
        </div>
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="-mt-1 -mr-1.5 inline-flex size-8 shrink-0 items-center justify-center rounded-md text-fg-subtle transition-colors duration-150 hover:bg-wash hover:text-fg"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
      {children && <div className="px-5 pt-4">{children}</div>}
      <div className="mt-6 flex justify-end gap-2 border-t border-line bg-wash px-5 py-3">{footer}</div>
    </dialog>
  );
}

// -- Drawer / sheet ----------------------------------------------------------------------------
const DRAWER_SIDE: Record<"left" | "right" | "bottom", { frame: string; enter: string; exit: string }> = {
  left: {
    frame: "inset-y-0 right-auto left-0 h-dvh w-[min(19rem,86vw)] border-r",
    enter: "drawer-enter-left",
    exit: "drawer-exit-left",
  },
  right: {
    frame: "inset-y-0 right-0 left-auto h-dvh w-[min(30rem,94vw)] border-l",
    enter: "drawer-enter-right",
    exit: "drawer-exit-right",
  },
  bottom: {
    frame: "inset-x-0 top-auto bottom-0 h-[min(88dvh,46rem)] w-full rounded-t-2xl border-t",
    enter: "drawer-enter-bottom",
    exit: "drawer-exit-bottom",
  },
};

interface DrawerProps {
  open: boolean;
  side: "left" | "right" | "bottom";
  label: string;
  onClose: () => void;
  children: ReactNode;
}

/**
 * A panel that slides in from an edge of the screen over a scrim: the navigation drawer on
 * small screens, and the source panel when there is no room to dock it. A modal <dialog>, so
 * focus stays inside it and Escape closes it.
 */
export function Drawer({ open, side, label, onClose, children }: DrawerProps) {
  const { mounted, closing } = usePresence(open);
  if (!mounted) return null;
  return (
    <DrawerDialog side={side} label={label} closing={closing} onClose={onClose}>
      {children}
    </DrawerDialog>
  );
}

function DrawerDialog({ side, label, closing, onClose, children }: Omit<DrawerProps, "open"> & { closing: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
    return () => dialog?.close();
  }, []);

  return (
    <dialog
      ref={ref}
      aria-label={label}
      data-closing={closing || undefined}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
      className={classNames(
        "fixed m-0 max-h-none max-w-none overflow-hidden border-line bg-surface p-0 shadow-xl",
        DRAWER_SIDE[side].frame,
        closing ? DRAWER_SIDE[side].exit : DRAWER_SIDE[side].enter,
      )}
    >
      {side === "bottom" && <div aria-hidden className="absolute top-2 left-1/2 z-10 h-1 w-9 -translate-x-1/2 rounded-full bg-line-strong" />}
      {children}
    </dialog>
  );
}
