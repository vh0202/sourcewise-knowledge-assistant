import { ChevronRight, ExternalLink, FolderOpen, X } from "lucide-react";
import { Fragment, useEffect, useRef, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";

import { FileTypeIcon, fileKindName, IconButton } from "../../components/ui";
import { classNames, pageLabel } from "../../lib/format";
import { scrollBehavior } from "../../lib/hooks";
import type { Citation } from "../../lib/types";

interface SourcePanelProps {
  citations: Citation[];
  activeNumber: number;
  /** Changes every time a citation is chosen, so that the cited text pulses again. */
  pulse: number;
  /** Move keyboard focus into the panel when it opens (it was opened from the keyboard, or it is modal). */
  autoFocus: boolean;
  /** Changes when a citation is chosen in the conversation, as opposed to a tab inside the panel. */
  openedAt: number;
  onSelect: (number: number) => void;
  onClose: () => void;
  /** Admins get a link from the passage to the chunk inspector. */
  canInspect: boolean;
}

/**
 * The passage behind a citation, laid out like a page of the document: the title, the trail
 * of section headings, the page number for PDFs, and the cited text highlighted in place.
 */
export function SourcePanel({ citations, activeNumber, pulse, autoFocus, openedAt, onSelect, onClose, canInspect }: SourcePanelProps) {
  const citation = citations.find((item) => item.number === activeNumber) ?? citations[0];
  const markRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const tabsRef = useRef<HTMLDivElement>(null);

  // Bring the cited text into view whenever a citation is chosen (again).
  useEffect(() => {
    markRef.current?.scrollIntoView({ block: "center", behavior: scrollBehavior() });
  }, [citation?.number, citation?.chunk_id, pulse]);

  useEffect(() => {
    if (autoFocus) closeRef.current?.focus({ preventScroll: true });
  }, [autoFocus, openedAt]);

  if (!citation) return null;
  const before = citation.passage.slice(0, citation.start_char);
  const quoted = citation.passage.slice(citation.start_char, citation.end_char);
  const after = citation.passage.slice(citation.end_char);
  const page = pageLabel(citation.page_start, citation.page_end);
  const headings = citation.heading_path.length ? citation.heading_path : ["Introduction"];
  const index = citations.findIndex((item) => item.number === citation.number);

  const onTabKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % citations.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + citations.length) % citations.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = citations.length - 1;
    else return;
    event.preventDefault();
    const target = citations[next];
    if (!target) return;
    onSelect(target.number);
    tabsRef.current?.querySelectorAll<HTMLElement>("[role='tab']")[next]?.focus();
  };

  return (
    <aside
      aria-label="Source"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onClose();
        }
      }}
      className="flex h-full w-full flex-col bg-sunken"
    >
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-surface px-4">
        <h2 className="text-base font-semibold text-fg">Source</h2>
        {citations.length > 1 ? (
          <div ref={tabsRef} role="tablist" aria-label="Sources of this answer" onKeyDown={onTabKeyDown} className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto py-1">
            {citations.map((item) => {
              const selected = item.number === citation.number;
              return (
                <button
                  key={item.number}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  aria-label={`Source ${item.number}: ${item.document_title}`}
                  tabIndex={selected ? 0 : -1}
                  onClick={() => onSelect(item.number)}
                  className={classNames(
                    "flex h-6 min-w-6 shrink-0 items-center justify-center rounded-sm px-1.5 text-xs font-semibold tabular-nums ring-1 ring-inset transition-colors duration-150 ease-standard",
                    selected ? "bg-cite-solid text-cite-solid-fg ring-mark-line" : "bg-cite text-cite-fg ring-cite-line hover:bg-cite-hover",
                  )}
                >
                  {item.number}
                </button>
              );
            })}
          </div>
        ) : (
          <span className="flex h-6 min-w-6 items-center justify-center rounded-sm bg-cite-solid px-1.5 text-xs font-semibold text-cite-solid-fg tabular-nums ring-1 ring-mark-line ring-inset">
            {citation.number}
          </span>
        )}
        <IconButton ref={closeRef} label="Close source panel" tooltipSide="bottom" onClick={onClose} className="-mr-1.5 ml-auto">
          <X className="size-4" aria-hidden />
        </IconButton>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-5">
        <div key={citation.number} className="animate-fade-in">
          <div className="flex items-start gap-3">
            <FileTypeIcon kind={citation.document_kind} />
            <div className="min-w-0">
              <h3 className="text-lg leading-snug font-semibold tracking-tight text-fg">{citation.document_title}</h3>
              <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-fg-muted">
                <span className="inline-flex items-center gap-1">
                  <FolderOpen className="size-3.5 text-fg-subtle" aria-hidden />
                  {citation.collection_name}
                </span>
                <span aria-hidden className="text-fg-faint">
                  ·
                </span>
                <span>{fileKindName(citation.document_kind)}</span>
              </p>
            </div>
          </div>

          {/* The page: a running head with the section trail and the page number, then the passage. */}
          <article className="mt-5 overflow-hidden rounded-xl border border-line bg-card shadow-sm">
            <div className="flex items-start justify-between gap-3 border-b border-line-faint px-4 py-2.5 sm:px-5">
              <nav aria-label="Section" className="min-w-0">
                <ol className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-xs text-fg-muted">
                  {headings.map((heading, position) => (
                    <Fragment key={position}>
                      {position > 0 && (
                        <li aria-hidden className="flex">
                          <ChevronRight className="size-3 text-fg-faint" />
                        </li>
                      )}
                      <li className={classNames(position === headings.length - 1 && "font-medium text-fg")}>{heading}</li>
                    </Fragment>
                  ))}
                </ol>
              </nav>
              {page && <span className="shrink-0 rounded-xs bg-wash px-1.5 py-0.5 text-2xs font-medium text-fg-muted tabular-nums">{page}</span>}
            </div>
            <blockquote className="max-w-[72ch] px-4 py-4 text-base leading-7 whitespace-pre-wrap text-fg-muted sm:px-5 [text-wrap:pretty]">
              {before}
              {/* Highlight line by line, so that blank lines inside a quotation are not painted. */}
              {quoted.split(/(\n+)/).map((piece, position) =>
                piece.startsWith("\n") || piece === "" ? (
                  piece
                ) : (
                  <mark key={`${pulse}-${position}`} ref={position === 0 ? markRef : undefined} data-pulse="true" className="cite-mark">
                    {piece}
                  </mark>
                ),
              )}
              {after}
            </blockquote>
          </article>

          <p className="mt-3 flex items-start gap-2 text-xs text-fg-subtle">
            <span aria-hidden className="mt-0.5 h-3 w-5 shrink-0 rounded-[3px] bg-mark shadow-[inset_0_-2px_0_var(--mark-line)]" />
            <span>The highlighted, underlined text is what the answer cites. The rest of the passage is shown for context.</span>
          </p>

          {canInspect && citation.document_id != null && (
            <Link
              to={`/knowledge/documents/${citation.document_id}${citation.chunk_id != null ? `#chunk-${citation.chunk_id}` : ""}`}
              className="mt-4 inline-flex items-center gap-1.5 rounded-xs text-sm font-medium text-accent-fg underline-offset-2 hover:underline"
            >
              Open in chunk inspector
              <ExternalLink className="size-3.5" aria-hidden />
            </Link>
          )}
        </div>
      </div>
    </aside>
  );
}
