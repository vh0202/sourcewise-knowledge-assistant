// Small line illustrations for empty states. They are drawn with the semantic colour tokens
// (paper, hairline, one accent and, where a citation is meant, the citation gold), so they
// follow the theme. All are decorative: the text beside them says the same thing.

import type { ReactNode } from "react";

import { classNames } from "../lib/format";

function Frame({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <svg viewBox="0 0 120 88" fill="none" aria-hidden className={classNames("h-[5.5rem] w-[7.5rem] shrink-0", className)}>
      {children}
    </svg>
  );
}

const PAPER = "fill-card stroke-line-strong";
const RULE = "stroke-line-strong";

/** A document under a magnifying glass, with one line missing: "not found in the knowledge base". */
export function NotFoundArt({ className }: { className?: string }) {
  return (
    <Frame className={className}>
      <rect x="24" y="15" width="50" height="62" rx="7" className={PAPER} strokeWidth="1.5" transform="rotate(-7 49 46)" />
      <rect x="35" y="9" width="50" height="64" rx="7" className={PAPER} strokeWidth="1.5" />
      <path d="M44 23h23M44 32h32" className={RULE} strokeWidth="3" strokeLinecap="round" />
      <path d="M44 41h32" className="stroke-accent" strokeWidth="3" strokeLinecap="round" strokeDasharray="0.1 6.3" />
      <path d="M44 50h26M44 59h17" className={RULE} strokeWidth="3" strokeLinecap="round" />
      <circle cx="82" cy="56" r="15.5" className="fill-surface stroke-accent" strokeWidth="2.5" />
      <path d="M93.5 67.5 104 78" className="stroke-accent" strokeWidth="4.5" strokeLinecap="round" />
      <path d="M75 56h14" className="stroke-fg-faint" strokeWidth="3" strokeLinecap="round" strokeDasharray="0.1 6.9" />
    </Frame>
  );
}

/** Two pages and an upward arrow: the upload drop zone and an empty document list. */
export function UploadArt({ className }: { className?: string }) {
  return (
    <Frame className={className}>
      <rect x="26" y="20" width="44" height="56" rx="7" className={PAPER} strokeWidth="1.5" transform="rotate(-9 48 48)" />
      <rect x="50" y="20" width="44" height="56" rx="7" className={PAPER} strokeWidth="1.5" transform="rotate(8 72 48)" />
      <rect x="38" y="10" width="44" height="58" rx="7" className={PAPER} strokeWidth="1.5" />
      <path d="M47 24h17M47 33h26M47 42h22" className={RULE} strokeWidth="3" strokeLinecap="round" />
      <circle cx="78" cy="62" r="14" className="fill-accent" />
      <path d="M78 68.5v-13m-5.5 5.5 5.5-5.5 5.5 5.5" className="stroke-white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </Frame>
  );
}

/** A page whose every line carries a citation chip: nothing was left unanswered. */
export function AllAnsweredArt({ className }: { className?: string }) {
  return (
    <Frame className={className}>
      <rect x="33" y="9" width="54" height="68" rx="7" className={PAPER} strokeWidth="1.5" />
      <path d="M43 24h22M43 36h27M43 48h18" className={RULE} strokeWidth="3" strokeLinecap="round" />
      <rect x="69" y="20" width="9" height="8" rx="2.5" className="fill-cite-solid" />
      <rect x="74" y="32" width="9" height="8" rx="2.5" className="fill-cite-solid" />
      <rect x="65" y="44" width="9" height="8" rx="2.5" className="fill-cite-solid" />
      <circle cx="84" cy="64" r="13" className="fill-success" />
      <path d="m78 64.5 4 4 8-8.5" className="stroke-white" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
    </Frame>
  );
}

/** Empty axes: there is nothing to chart yet. */
export function NoDataArt({ className }: { className?: string }) {
  return (
    <Frame className={className}>
      <rect x="18" y="10" width="84" height="64" rx="8" className={PAPER} strokeWidth="1.5" />
      <path d="M30 60h60" className="stroke-fg-faint" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M30 44h60M30 28h60" className={RULE} strokeWidth="1.5" strokeLinecap="round" strokeDasharray="0.1 5" />
      <rect x="37" y="48" width="8" height="12" rx="2" className="fill-wash-strong" />
      <rect x="52" y="40" width="8" height="20" rx="2" className="fill-wash-strong" />
      <rect x="67" y="33" width="8" height="27" rx="2" className="fill-accent" opacity="0.55" />
      <rect x="82" y="45" width="8" height="15" rx="2" className="fill-wash-strong" />
    </Frame>
  );
}

/** A page with a padlock: administrators only. */
export function LockedArt({ className }: { className?: string }) {
  return (
    <Frame className={className}>
      <rect x="35" y="9" width="50" height="66" rx="7" className={PAPER} strokeWidth="1.5" />
      <path d="M44 23h24M44 32h32M44 41h20" className={RULE} strokeWidth="3" strokeLinecap="round" />
      <rect x="66" y="50" width="30" height="24" rx="6" className="fill-accent" />
      <path d="M73 50v-5a8 8 0 0 1 16 0v5" className="stroke-accent" strokeWidth="3.5" strokeLinecap="round" />
      <circle cx="81" cy="61" r="2.6" className="fill-white" />
      <path d="M81 62v5" className="stroke-white" strokeWidth="2.4" strokeLinecap="round" />
    </Frame>
  );
}

/** A signpost with a blank board: there is nothing at this address. */
export function LostArt({ className }: { className?: string }) {
  return (
    <Frame className={className}>
      <path d="M60 14v62" className="stroke-fg-faint" strokeWidth="3" strokeLinecap="round" />
      <path d="M42 76h36" className={RULE} strokeWidth="3" strokeLinecap="round" />
      <path d="M36 20h44l9 9-9 9H36a3 3 0 0 1-3-3V23a3 3 0 0 1 3-3Z" className="fill-card stroke-accent" strokeWidth="2" strokeLinejoin="round" />
      <path d="M43 29h24" className="stroke-accent" strokeWidth="3" strokeLinecap="round" strokeDasharray="0.1 6" />
      <path d="M84 46H42l-9 8 9 8h42a3 3 0 0 0 3-3V49a3 3 0 0 0-3-3Z" className={PAPER} strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M50 54h26" className={RULE} strokeWidth="3" strokeLinecap="round" />
    </Frame>
  );
}

/** Two speech bubbles, the second carrying a citation chip: an empty conversation list. */
export function ConversationArt({ className }: { className?: string }) {
  return (
    <Frame className={className}>
      <path d="M30 18h42a7 7 0 0 1 7 7v16a7 7 0 0 1-7 7H47l-9 8v-8h-8a7 7 0 0 1-7-7V25a7 7 0 0 1 7-7Z" className={PAPER} strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M33 29h30M33 38h20" className={RULE} strokeWidth="3" strokeLinecap="round" />
      <path d="M56 40h36a7 7 0 0 1 7 7v15a7 7 0 0 1-7 7h-4v8l-9-8H56a7 7 0 0 1-7-7V47a7 7 0 0 1 7-7Z" className="fill-accent-soft-strong stroke-accent" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M59 51h20M59 60h12" className="stroke-accent" strokeWidth="3" strokeLinecap="round" />
      <rect x="83" y="47" width="9" height="8" rx="2.5" className="fill-cite-solid" />
    </Frame>
  );
}
