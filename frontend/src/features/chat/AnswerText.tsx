import { Fragment, useEffect, useId, useRef, useState, type ReactNode } from "react";

import { Floating } from "../../components/overlays";
import { FileTypeIcon } from "../../components/ui";
import { pageLabel, sectionLabel } from "../../lib/format";
import type { Citation } from "../../lib/types";

const MARKER = /(\[\d+\])/;
const BOLD = /(\*\*[^*\n]+\*\*)/;

/** What a citation points at: document, section, page and the cited sentence. Shown on hover. */
function CitationPreview({ id, citation }: { id: string; citation: Citation }) {
  const page = pageLabel(citation.page_start, citation.page_end);
  return (
    <div id={id} role="tooltip" className="w-80 max-w-[calc(100vw-1rem)] animate-pop rounded-xl border border-line bg-raised p-3.5 text-left shadow-lg">
      <div className="flex items-start gap-2.5">
        <FileTypeIcon kind={citation.document_kind} size="sm" className="mt-0.5" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-fg">{citation.document_title}</p>
          <p className="truncate text-xs text-fg-muted">{sectionLabel(citation.heading_path)}</p>
        </div>
        {page && <span className="shrink-0 rounded-xs bg-wash px-1.5 py-0.5 text-2xs font-medium text-fg-muted tabular-nums">{page}</span>}
      </div>
      <p className="mt-3 line-clamp-4 border-l-2 border-mark-line pl-3 text-sm leading-relaxed text-fg">{citation.quote.replace(/\s+/g, " ").trim()}</p>
      <p className="mt-2.5 text-2xs text-fg-subtle">Select the number to read the passage in context.</p>
    </div>
  );
}

interface ChipProps {
  citation: Citation;
  active: boolean;
  onCite?: (number: number, viaKeyboard: boolean) => void;
}

/** A numbered citation in the answer. Hover or focus previews the cited sentence; click opens the source. */
function CitationChip({ citation, active, onCite }: ChipProps) {
  const button = useRef<HTMLButtonElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const [open, setOpen] = useState(false);
  const previewId = useId();

  const schedule = (next: boolean, delay: number) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(next), delay);
  };

  useEffect(() => () => window.clearTimeout(timer.current), []);

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    const onKeyDown = (event: KeyboardEvent) => event.key === "Escape" && close();
    window.addEventListener("scroll", close, true);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <>
      <button
        ref={button}
        type="button"
        className="citation-chip"
        aria-pressed={active}
        aria-label={`Show source ${citation.number}: ${citation.document_title}`}
        aria-describedby={open ? previewId : undefined}
        onClick={(event) => {
          schedule(false, 0);
          onCite?.(citation.number, event.detail === 0);
        }}
        onMouseEnter={() => schedule(true, 180)}
        onMouseLeave={() => schedule(false, 80)}
        onFocus={(event) => event.target.matches(":focus-visible") && schedule(true, 0)}
        onBlur={() => schedule(false, 0)}
      >
        {citation.number}
      </button>
      <Floating open={open} anchor={() => button.current} side="top" gap={8} className="pointer-events-none">
        <CitationPreview id={previewId} citation={citation} />
      </Floating>
    </>
  );
}

interface AnswerTextProps {
  content: string;
  /** The citations of this answer; only their numbers become chips. */
  citations: Citation[];
  active: number | null;
  onCite?: (number: number, viaKeyboard: boolean) => void;
  /** The answer is still arriving: new words fade in, citations are not selectable yet, a caret follows the text. */
  streaming?: boolean;
}

/**
 * Renders answer text: paragraphs, line breaks, simple "- " lists, **bold**, and the "[n]"
 * markers as citation chips. Deliberately not a Markdown engine - the text is either a
 * verbatim quotation or a short model answer, and it is never rendered as HTML.
 */
export function AnswerText({ content, citations, active, onCite, streaming = false }: AnswerTextProps) {
  const byNumber = new Map(citations.map((citation) => [citation.number, citation]));

  /** Plain text. While streaming, each word is its own element so that only the new ones fade in. */
  const words = (text: string, key: string): ReactNode =>
    streaming
      ? text.split(/(\s+)/).map((word, index) =>
          /^\s*$/.test(word) ? (
            word
          ) : (
            <span key={`${key}-w${index}`} className="animate-word">
              {word}
            </span>
          ),
        )
      : text;

  const inline = (text: string, keyPrefix: string): ReactNode[] =>
    text.split(MARKER).flatMap((piece, index) => {
      const key = `${keyPrefix}-${index}`;
      const match = /^\[(\d+)\]$/.exec(piece);
      if (match) {
        const number = Number(match[1]);
        const citation = byNumber.get(number);
        if (!citation) {
          // While streaming, the citation exists but is not selectable yet; otherwise it is plain text.
          return streaming
            ? [
                <span key={key} className="citation-chip animate-word">
                  {number}
                </span>,
              ]
            : [<Fragment key={key}>{piece}</Fragment>];
        }
        return [<CitationChip key={key} citation={citation} active={active === number} onCite={onCite} />];
      }
      return piece.split(BOLD).map((part, partIndex) =>
        part.startsWith("**") && part.endsWith("**") && part.length > 4 ? (
          <strong key={`${key}-${partIndex}`} className="font-semibold text-fg">
            {words(part.slice(2, -2), `${key}-${partIndex}`)}
          </strong>
        ) : (
          <Fragment key={`${key}-${partIndex}`}>{words(part, `${key}-${partIndex}`)}</Fragment>
        ),
      );
    });

  const paragraphs = content.split(/\n{2,}/).filter((paragraph) => paragraph.trim().length > 0);
  const caret = streaming ? (
    <span className="ml-0.5 inline-block h-[1.05em] w-0.5 translate-y-[0.2em] animate-caret rounded-full bg-accent" aria-hidden />
  ) : null;

  return (
    <div className="max-w-[64ch] space-y-3.5 text-md text-fg [text-wrap:pretty]">
      {paragraphs.map((paragraph, paragraphIndex) => {
        const lines = paragraph.split("\n").filter((line) => line.trim().length > 0);
        const isLast = paragraphIndex === paragraphs.length - 1;
        const key = `p${paragraphIndex}`;
        if (lines.length > 1 && lines.every((line) => /^[-•]\s+/.test(line.trim()))) {
          return (
            <ul key={key} className="list-disc space-y-1.5 pl-5 marker:text-fg-faint">
              {lines.map((line, lineIndex) => (
                <li key={lineIndex}>
                  {inline(line.trim().replace(/^[-•]\s+/, ""), `${key}-${lineIndex}`)}
                  {isLast && lineIndex === lines.length - 1 && caret}
                </li>
              ))}
            </ul>
          );
        }
        return (
          <p key={key}>
            {lines.map((line, lineIndex) => (
              <Fragment key={lineIndex}>
                {lineIndex > 0 && <br />}
                {inline(line, `${key}-${lineIndex}`)}
              </Fragment>
            ))}
            {isLast && caret}
          </p>
        );
      })}
      {paragraphs.length === 0 && caret && <p>{caret}</p>}
    </div>
  );
}
