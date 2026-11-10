// Presentational building blocks shared by every page. All colours come from the semantic
// tokens in styles/tokens.css, so each component works in the light and the dark theme.

import { CircleAlert, LoaderCircle } from "lucide-react";
import { useId, useRef, type ComponentProps, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";

import { classNames } from "../lib/format";
import { useActiveIndicator } from "../lib/hooks";
import { Tooltip, type Side } from "./overlays";

// -- Button ------------------------------------------------------------------------------------
type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md" | "lg";

const BUTTON_VARIANT: Record<ButtonVariant, string> = {
  // Filled buttons have depth: a light edge on top, a hairline ring and a soft drop shadow.
  primary: "bg-accent bg-linear-to-b from-white/10 to-white/0 text-on-accent shadow-button hover:bg-accent-hover active:brightness-95",
  secondary: "bg-control text-fg shadow-control hover:bg-control-hover active:bg-wash-strong",
  ghost: "text-fg-muted hover:bg-wash hover:text-fg active:bg-wash-strong",
  danger: "bg-danger bg-linear-to-b from-white/10 to-white/0 text-white shadow-button-danger hover:bg-danger-hover active:brightness-95",
};

const BUTTON_SIZE: Record<ButtonSize, string> = {
  sm: "h-7 gap-1.5 px-2.5 text-xs",
  md: "h-8 gap-1.5 px-3 text-sm",
  lg: "h-10 gap-2 px-4 text-base",
};

interface ButtonProps extends ComponentProps<"button"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: ReactNode;
}

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  icon,
  className,
  children,
  disabled,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={classNames(
        "inline-flex shrink-0 items-center justify-center rounded-md font-medium whitespace-nowrap select-none",
        "transition-[background-color,box-shadow,color,filter,transform] duration-150 ease-standard",
        "active:translate-y-px disabled:pointer-events-none disabled:opacity-50",
        BUTTON_SIZE[size],
        BUTTON_VARIANT[variant],
        className,
      )}
      {...rest}
    >
      {loading ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

interface IconButtonProps extends ComponentProps<"button"> {
  /** The accessible name, also shown as a tooltip. */
  label: string;
  active?: boolean;
  size?: "sm" | "md";
  tooltipSide?: Side;
  shortcut?: string;
}

/** A square, icon-only button. */
export function IconButton({
  label,
  active = false,
  size = "md",
  tooltipSide = "top",
  shortcut,
  className,
  children,
  type = "button",
  ...rest
}: IconButtonProps) {
  return (
    <Tooltip label={label} side={tooltipSide} shortcut={shortcut}>
      <button
        type={type}
        aria-label={label}
        className={classNames(
          "inline-flex shrink-0 items-center justify-center rounded-md transition-colors duration-150 ease-standard",
          "disabled:pointer-events-none disabled:text-fg-faint",
          size === "sm" ? "size-7" : "size-8",
          active ? "bg-accent-soft text-accent-fg" : "text-fg-subtle hover:bg-wash hover:text-fg active:bg-wash-strong",
          className,
        )}
        {...rest}
      >
        {children}
      </button>
    </Tooltip>
  );
}

// -- Badge -------------------------------------------------------------------------------------
type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "cite";

const TONES: Record<Tone, string> = {
  neutral: "bg-wash text-fg-muted ring-line",
  accent: "bg-accent-soft text-accent-fg ring-accent-line",
  success: "bg-success-soft text-success-fg ring-success-line",
  warning: "bg-warning-soft text-warning-fg ring-warning-line",
  danger: "bg-danger-soft text-danger-fg ring-danger-line",
  cite: "bg-cite text-cite-fg ring-cite-line",
};

export function Badge({ tone = "neutral", icon, children, className }: { tone?: Tone; icon?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <span
      className={classNames(
        "inline-flex h-5 items-center gap-1 rounded-full px-2 text-xs font-medium whitespace-nowrap ring-1 ring-inset",
        TONES[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

/** A key cap, for keyboard hints. */
export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={classNames(
        "inline-flex h-5 min-w-5 items-center justify-center rounded-xs border border-line bg-sunken px-1 font-sans text-2xs font-medium text-fg-subtle",
        className,
      )}
    >
      {children}
    </kbd>
  );
}

// -- File types --------------------------------------------------------------------------------
const FILE_KIND: Record<string, { tag: string; name: string; fill: string; background: string; width: number }> = {
  pdf: { tag: "PDF", name: "PDF", fill: "fill-file-pdf", background: "bg-file-pdf", width: 18 },
  md: { tag: "MD", name: "Markdown", fill: "fill-file-md", background: "bg-file-md", width: 15 },
  txt: { tag: "TXT", name: "Plain text", fill: "fill-file-txt", background: "bg-file-txt", width: 18 },
  html: { tag: "HTML", name: "HTML", fill: "fill-file-html", background: "bg-file-html", width: 22 },
};

function fileKind(kind: string) {
  return FILE_KIND[kind] ?? { tag: kind.slice(0, 4).toUpperCase(), name: kind.toUpperCase(), fill: "fill-file-txt", background: "bg-file-txt", width: 18 };
}

/** "PDF", "Markdown", "Plain text" or "HTML". */
export function fileKindName(kind: string): string {
  return fileKind(kind).name;
}

const FILE_ICON_SIZE = { md: "h-[34px] w-[30px]", lg: "h-11 w-[39px]" };

/**
 * The file type of a document. At the regular sizes it is a page with a folded corner and a
 * coloured tag; `sm` is the tag alone, for dense rows. The tag carries the type as text, so the
 * colour is never the only cue.
 */
export function FileTypeIcon({ kind, size = "md", className }: { kind: string; size?: "sm" | keyof typeof FILE_ICON_SIZE; className?: string }) {
  const { tag, fill, background, width } = fileKind(kind);
  if (size === "sm") {
    return (
      <span
        className={classNames(
          "inline-flex h-[1.125rem] w-8 shrink-0 items-center justify-center rounded-xs text-[0.5625rem] leading-none font-bold tracking-wide text-white",
          background,
          className,
        )}
      >
        {tag}
      </span>
    );
  }
  return (
    <svg viewBox="0 0 30 34" className={classNames("shrink-0", FILE_ICON_SIZE[size], className)} aria-hidden>
      <path
        d="M8.5 1.5h10.7c.6 0 1.1.2 1.5.6l6.2 6.2c.4.4.6.9.6 1.5V29a3.5 3.5 0 0 1-3.5 3.5H8.5A3.5 3.5 0 0 1 5 29V5a3.5 3.5 0 0 1 3.5-3.5Z"
        className="fill-file-page stroke-file-edge"
        strokeWidth="1"
      />
      <path d="M19.5 2v4.5a3 3 0 0 0 3 3H27" className="stroke-file-edge" strokeWidth="1" fill="none" />
      <rect x="0.5" y="16.5" width={width} height="10" rx="2.5" className={fill} />
      <text x={0.5 + width / 2} y="23.9" textAnchor="middle" className="fill-white" fontSize="6.4" fontWeight="700" letterSpacing="0.15">
        {tag}
      </text>
    </svg>
  );
}

// -- Feedback states ---------------------------------------------------------------------------
/** A placeholder block with a slow shimmer; size it with utility classes. */
export function Skeleton({ className, style }: { className?: string; style?: CSSProperties }) {
  return <span aria-hidden style={style} className={classNames("skeleton block", className)} />;
}

export function ErrorNotice({ message, onRetry, className }: { message: string; onRetry?: () => void; className?: string }) {
  return (
    <div
      role="alert"
      className={classNames(
        "flex items-start gap-2.5 rounded-lg border border-danger-line bg-danger-soft px-3.5 py-3 text-sm text-danger-fg",
        className,
      )}
    >
      <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
      <p className="min-w-0 flex-1">{message}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="shrink-0 rounded-xs font-medium underline underline-offset-2 hover:no-underline">
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  illustration,
  title,
  children,
  action,
  className,
}: {
  illustration: ReactNode;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={classNames("flex flex-col items-center justify-center px-6 py-12 text-center", className)}>
      {illustration}
      <h3 className="mt-5 text-base font-semibold text-fg">{title}</h3>
      {children && <p className="mt-1 max-w-sm text-sm text-fg-muted">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

// -- Card --------------------------------------------------------------------------------------
export function Card({ className, children, ...rest }: ComponentProps<"section">) {
  return (
    <section className={classNames("rounded-xl border border-line bg-card shadow-xs", className)} {...rest}>
      {children}
    </section>
  );
}

export function CardHeader({ title, description, action }: { title: string; description?: ReactNode; action?: ReactNode }) {
  return (
    <header className="flex items-start justify-between gap-4 px-5 pt-4 pb-3">
      <div className="min-w-0">
        <h2 className="text-base font-semibold text-fg">{title}</h2>
        {description && <p className="mt-0.5 text-sm text-fg-muted">{description}</p>}
      </div>
      {action}
    </header>
  );
}

// -- Form field --------------------------------------------------------------------------------
export function Field({ label, hint, children }: { label: string; hint?: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-fg">
        {label}
      </label>
      <div className="mt-1.5">{children(id)}</div>
      {hint && <p className="mt-1.5 text-xs text-fg-subtle">{hint}</p>}
    </div>
  );
}

export const INPUT_CLASS =
  "block w-full rounded-md bg-control px-3 py-2 text-base text-fg shadow-control transition-shadow duration-150 ease-standard placeholder:text-fg-subtle focus:shadow-focus focus:outline-none";

export const SELECT_CLASS =
  "rounded-md bg-control py-1 pr-7 pl-2.5 text-sm font-medium text-fg shadow-control transition-shadow duration-150 ease-standard hover:bg-control-hover focus:shadow-focus focus:outline-none disabled:opacity-50";

// -- Segmented control -------------------------------------------------------------------------
interface Option<T> {
  value: T;
  label: ReactNode;
  /** A number shown after the label. */
  count?: number;
}

interface ChoiceProps<T> {
  /** Accessible name of the group. */
  label: string;
  value: T;
  options: Option<T>[];
  onChange: (value: T) => void;
  className?: string;
}

/** A row of mutually exclusive buttons; the selected one sits on a thumb that slides between them. */
export function Segmented<T extends string | number>({ label, value, options, onChange, className }: ChoiceProps<T>) {
  const ref = useRef<HTMLDivElement>(null);
  const thumb = useActiveIndicator(ref, value);
  return (
    <div ref={ref} role="group" aria-label={label} className={classNames("relative inline-flex rounded-lg bg-wash p-0.5", className)}>
      {thumb && (
        <span
          aria-hidden
          className="absolute inset-y-0.5 rounded-md bg-thumb shadow-sm ring-1 ring-line transition-[left,width] duration-200 ease-out"
          style={{ left: thumb.left, width: thumb.width }}
        />
      )}
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={String(option.value)}
            type="button"
            aria-pressed={active}
            data-active={active}
            onClick={() => onChange(option.value)}
            className={classNames(
              "relative z-10 h-7 rounded-md px-3 text-sm font-medium whitespace-nowrap transition-colors duration-150 ease-standard",
              active ? "text-fg" : "text-fg-muted hover:text-fg",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

// -- Tabs --------------------------------------------------------------------------------------
/** Underlined tabs with a sliding indicator. Arrow keys move between tabs. */
export function Tabs<T extends string | number>({ label, value, options, onChange, className, controls }: ChoiceProps<T> & { controls?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const indicator = useActiveIndicator(ref, value);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = options.findIndex((option) => option.value === value);
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % options.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + options.length) % options.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = options.length - 1;
    else return;
    event.preventDefault();
    const option = options[next];
    if (!option) return;
    onChange(option.value);
    ref.current?.querySelectorAll<HTMLElement>("[role='tab']")[next]?.focus();
  };

  return (
    <div ref={ref} role="tablist" aria-label={label} onKeyDown={onKeyDown} className={classNames("relative flex min-w-0 gap-1", className)}>
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={String(option.value)}
            type="button"
            role="tab"
            aria-selected={active}
            aria-controls={controls}
            tabIndex={active ? 0 : -1}
            data-active={active}
            onClick={() => onChange(option.value)}
            className={classNames(
              "relative flex h-10 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-sm font-medium whitespace-nowrap transition-colors duration-150 ease-standard",
              active ? "text-fg" : "text-fg-muted hover:text-fg",
            )}
          >
            {option.label}
            {option.count != null && (
              <span
                className={classNames(
                  "rounded-full px-1.5 text-2xs leading-4 font-medium tabular-nums transition-colors duration-150",
                  active ? "bg-accent-soft-strong text-accent-fg" : "bg-wash text-fg-subtle",
                )}
              >
                {option.count}
              </span>
            )}
          </button>
        );
      })}
      {indicator && (
        <span
          aria-hidden
          className="absolute bottom-0 h-0.5 rounded-full bg-accent transition-[left,width] duration-200 ease-out"
          style={{ left: indicator.left + 10, width: Math.max(indicator.width - 20, 0) }}
        />
      )}
    </div>
  );
}
