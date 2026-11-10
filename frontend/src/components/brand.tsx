import { Sparkles } from "lucide-react";
import { useId } from "react";

import { classNames } from "../lib/format";
import { Tooltip, type Side } from "./overlays";

/** The product mark: lines of text ending in a citation chip. */
export function LogoMark({ className }: { className?: string }) {
  const gradient = useId();
  return (
    <svg viewBox="0 0 32 32" className={classNames("shrink-0", className ?? "size-7")} aria-hidden>
      <defs>
        <linearGradient id={gradient} x1="4" y1="2" x2="28" y2="30" gradientUnits="userSpaceOnUse">
          <stop stopColor="#8076fa" />
          <stop offset="1" stopColor="#523bc3" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill={`url(#${gradient})`} />
      <path d="M9 10.5h14M9 16h14M9 21.5h5.5" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" />
      <rect x="17.5" y="18.25" width="6.5" height="6.5" rx="2" fill="#f9bc2c" />
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={classNames("inline-flex items-center gap-2.5", className)}>
      <LogoMark />
      <span className="text-lg font-semibold tracking-tight text-fg">SourceWise</span>
    </span>
  );
}

const ENGINE_NOTE = {
  claude: "Answers are written by Claude from the retrieved passages, with a citation for every statement.",
  offline: "Answers are verbatim quotations from the best-matching passages. No API key is configured, so no model is called.",
};

interface EngineChipProps {
  engine: string | null;
  label: string | null;
  /** Shown instead of the label below the `sm` breakpoint, where the header has little room. */
  shortLabel?: string;
  size?: "sm" | "md";
  /** Explain the engine in a tooltip and make the chip reachable from the keyboard. */
  explain?: boolean;
  tooltipSide?: Side;
  className?: string;
}

/**
 * Which engine produced (or will produce) an answer, as a status chip. The offline engine is
 * always labelled "Extractive (offline) mode" so that nobody mistakes verbatim quotation for a
 * model's answer. The two states differ in wording and glyph, not only in colour: a hollow
 * ring for the offline engine, a spark for Claude.
 */
export function EngineChip({ engine, label, shortLabel, size = "md", explain = false, tooltipSide = "bottom", className }: EngineChipProps) {
  const isClaude = engine === "claude";
  const text = label ?? (isClaude ? "Claude" : "Extractive (offline) mode");
  const chip = (
    <span
      tabIndex={explain ? 0 : undefined}
      role={explain ? "status" : undefined}
      aria-label={explain ? `Answer engine: ${text}. ${isClaude ? ENGINE_NOTE.claude : ENGINE_NOTE.offline}` : undefined}
      className={classNames(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full font-medium whitespace-nowrap ring-1 ring-inset",
        size === "sm" ? "h-[22px] px-2 text-xs" : "h-7 px-2.5 text-xs",
        isClaude ? "bg-accent-soft text-accent-fg ring-accent-line" : "bg-wash text-fg-muted ring-line",
        className,
      )}
    >
      {isClaude ? (
        <Sparkles className="size-3" aria-hidden />
      ) : (
        <span aria-hidden className="size-2 rounded-full border-[1.5px] border-fg-subtle" />
      )}
      {shortLabel ? (
        <>
          <span className="sm:hidden">{shortLabel}</span>
          <span className="hidden sm:inline">{text}</span>
        </>
      ) : (
        text
      )}
    </span>
  );
  if (!explain) return chip;
  return (
    <Tooltip label={isClaude ? ENGINE_NOTE.claude : ENGINE_NOTE.offline} side={tooltipSide} align="end">
      {chip}
    </Tooltip>
  );
}
