import { ArrowUpRight, Check, Copy, Info, ThumbsDown, ThumbsUp, TriangleAlert } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { EngineChip, LogoMark } from "../../components/brand";
import { NotFoundArt } from "../../components/illustrations";
import { Tooltip } from "../../components/overlays";
import { useToast } from "../../components/toast";
import { FileTypeIcon, IconButton, Skeleton } from "../../components/ui";
import { classNames, formatPercent, pageLabel, sectionLabel } from "../../lib/format";
import type { Citation, EngineInfo, Message } from "../../lib/types";
import { AnswerText } from "./AnswerText";

export function UserMessage({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-bubble px-4 py-2.5 text-md whitespace-pre-wrap text-fg">
        <span className="sr-only">You asked: </span>
        {content}
      </div>
    </div>
  );
}

function AssistantFrame({ id, animate = true, busy = false, children }: { id?: string; animate?: boolean; busy?: boolean; children: ReactNode }) {
  return (
    <article id={id} aria-busy={busy || undefined} className={classNames("flex scroll-mt-20 scroll-mb-4 gap-3.5", animate && "animate-rise")}>
      <LogoMark className="mt-0.5 hidden size-7 sm:block" />
      <div className="min-w-0 flex-1">{children}</div>
    </article>
  );
}

function SourceList({ citations, active, onCite }: { citations: Citation[]; active: number | null; onCite: (number: number, viaKeyboard: boolean) => void }) {
  return (
    <div className="mt-5 animate-fade-in">
      <h3 className="text-2xs font-medium tracking-caps text-fg-subtle uppercase">Sources</h3>
      <ol className={classNames("mt-2 grid gap-2", citations.length > 1 && "sm:grid-cols-2")}>
        {citations.map((citation) => {
          const page = pageLabel(citation.page_start, citation.page_end);
          const selected = active === citation.number;
          return (
            <li key={citation.number} className="min-w-0">
              <button
                type="button"
                onClick={(event) => onCite(citation.number, event.detail === 0)}
                aria-pressed={selected}
                className={classNames(
                  "group/source flex h-full w-full items-center gap-3 rounded-lg border bg-card px-3 py-2.5 text-left transition-[border-color,box-shadow,background-color] duration-150 ease-standard",
                  selected ? "border-cite-line shadow-[0_0_0_3px_var(--cite)]" : "border-line shadow-xs hover:border-line-strong hover:bg-sunken",
                )}
              >
                <span
                  className={classNames(
                    "flex size-5 shrink-0 items-center justify-center rounded-[0.3125rem] text-2xs font-semibold tabular-nums ring-1 ring-inset transition-colors duration-150",
                    selected ? "bg-cite-solid text-cite-solid-fg ring-mark-line" : "bg-cite text-cite-fg ring-cite-line",
                  )}
                >
                  {citation.number}
                </span>
                <FileTypeIcon kind={citation.document_kind} size="sm" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-fg">{citation.document_title}</span>
                  <span className="block truncate text-xs text-fg-muted">
                    {sectionLabel(citation.heading_path)}
                    {page && <span className="tabular-nums"> · {page}</span>}
                  </span>
                </span>
                <ArrowUpRight
                  className={classNames(
                    "size-3.5 shrink-0 text-fg-subtle transition-opacity duration-150",
                    selected ? "opacity-100" : "opacity-0 group-hover/source:opacity-100 group-focus-visible/source:opacity-100",
                  )}
                  aria-hidden
                />
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/**
 * The abstention: a calm, deliberate state rather than an error. The assistant only answers
 * from the documents, and here it says that they do not cover the question.
 */
function NotFoundCard({ message, isAdmin }: { message: Message; isAdmin: boolean }) {
  const refused = message.abstain_reason === "refused";
  return (
    <div className="flex max-w-[68ch] items-start gap-4 rounded-xl border border-dashed border-line-strong bg-sunken px-4 py-4 sm:px-5">
      <NotFoundArt className="mt-0.5 hidden h-16 w-[5.5rem] sm:block" />
      <div className="min-w-0">
        <p className="text-base font-semibold text-fg">{refused ? "No answer available" : "Not found in the knowledge base"}</p>
        <p className="mt-1 text-sm text-fg-muted">
          {refused
            ? message.content
            : "None of the passages I found covers this question, and I only answer from the documents that have been added. Nothing was guessed."}
        </p>
        {!refused && (
          <p className="mt-2.5 text-sm text-fg-muted">
            {isAdmin ? (
              <>
                It has been logged as a knowledge gap.{" "}
                <Link to="/knowledge" className="font-medium text-accent-fg underline-offset-2 hover:underline">
                  Add a document
                </Link>{" "}
                that covers it, or{" "}
                <Link to="/insights" className="font-medium text-accent-fg underline-offset-2 hover:underline">
                  review the open gaps
                </Link>
                .
              </>
            ) : (
              "Try different wording, or ask an administrator to add a document that covers it."
            )}
          </p>
        )}
      </div>
    </div>
  );
}

function plainTextForCopy(message: Message): string {
  if (!message.citations.length) return message.content;
  const sources = message.citations.map((citation) => {
    const page = pageLabel(citation.page_start, citation.page_end);
    return `[${citation.number}] ${citation.document_title} - ${sectionLabel(citation.heading_path)}${page ? `, ${page.toLowerCase()}` : ""}`;
  });
  return `${message.content}\n\nSources:\n${sources.join("\n")}`;
}

const RETRIEVAL_NOTE =
  "Share of the question's key terms found in the best-matching passage. Below the threshold, the assistant declines to answer.";

/** How much of the question's key vocabulary the best passage contains, as a small meter. */
function RetrievalMatch({ confidence }: { confidence: number }) {
  const share = Math.min(Math.max(confidence, 0), 1);
  return (
    <Tooltip label={RETRIEVAL_NOTE}>
      <span
        tabIndex={0}
        role="img"
        aria-label={`Retrieval match ${formatPercent(confidence)}. ${RETRIEVAL_NOTE}`}
        className="inline-flex items-center gap-2 rounded-xs text-xs text-fg-subtle"
      >
        <span aria-hidden className="h-1 w-10 overflow-hidden rounded-full bg-series-1-soft">
          <span className="block h-full origin-left animate-grow-x rounded-full bg-series-1" style={{ width: `${share * 100}%` }} />
        </span>
        <span>
          Retrieval match <span className="font-medium text-fg-muted tabular-nums">{formatPercent(confidence)}</span>
        </span>
      </span>
    </Tooltip>
  );
}

interface AssistantMessageProps {
  id?: string;
  message: Message;
  activeCitation: number | null;
  isAdmin: boolean;
  /** False for the answer that has just finished streaming: it is already on screen. */
  animate?: boolean;
  onCite: (number: number, viaKeyboard: boolean) => void;
  onFeedback: (value: -1 | 0 | 1) => void;
}

export function AssistantMessage({ id, message, activeCitation, isAdmin, animate = true, onCite, onFeedback }: AssistantMessageProps) {
  const [copied, setCopied] = useState(false);
  const toast = useToast();
  const isPrompt = message.abstain_reason === "empty_query";

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(plainTextForCopy(message));
      setCopied(true);
      toast({ title: "Answer copied", description: message.citations.length ? "The list of sources is included." : undefined });
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
      toast({ title: "Could not copy the answer", tone: "danger" });
    }
  };

  return (
    <AssistantFrame id={id} animate={animate}>
      {message.notice && (
        <p className="mb-3 flex max-w-[64ch] items-start gap-2 rounded-lg border border-warning-line bg-warning-soft px-3 py-2 text-sm text-warning-fg">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {message.notice}
        </p>
      )}

      {message.abstained ? (
        isPrompt ? (
          <p className="max-w-[64ch] text-md text-fg">{message.content}</p>
        ) : (
          <NotFoundCard message={message} isAdmin={isAdmin} />
        )
      ) : (
        <>
          <AnswerText content={message.content} citations={message.citations} active={activeCitation} onCite={onCite} />
          {message.truncated && (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-fg-subtle">
              <Info className="size-3.5" aria-hidden />
              This answer was cut short because it reached the length limit.
            </p>
          )}
          {message.citations.length > 0 && <SourceList citations={message.citations} active={activeCitation} onCite={onCite} />}
        </>
      )}

      <div className="mt-3 flex min-h-8 flex-wrap items-center gap-x-3 gap-y-2">
        <EngineChip engine={message.engine} label={message.engine_label} size="sm" />
        {message.confidence != null && !isPrompt && <RetrievalMatch confidence={message.confidence} />}
        {!isPrompt && (
          <div className="ml-auto flex items-center gap-0.5">
            {!message.abstained && (
              <IconButton label={copied ? "Copied" : "Copy answer"} onClick={() => void copy()}>
                {copied ? <Check className="size-4 text-success-fg" aria-hidden /> : <Copy className="size-4" aria-hidden />}
              </IconButton>
            )}
            <IconButton
              label="Helpful"
              aria-pressed={message.feedback === 1}
              active={message.feedback === 1}
              onClick={() => onFeedback(message.feedback === 1 ? 0 : 1)}
            >
              <ThumbsUp className="size-4" fill={message.feedback === 1 ? "currentColor" : "none"} fillOpacity={0.22} aria-hidden />
            </IconButton>
            <IconButton
              label="Not helpful"
              aria-pressed={message.feedback === -1}
              active={message.feedback === -1}
              onClick={() => onFeedback(message.feedback === -1 ? 0 : -1)}
            >
              <ThumbsDown className="size-4" fill={message.feedback === -1 ? "currentColor" : "none"} fillOpacity={0.22} aria-hidden />
            </IconButton>
          </div>
        )}
      </div>
    </AssistantFrame>
  );
}

interface PendingAnswerProps {
  text: string;
  phase: "searching" | "writing";
  engine: EngineInfo | null;
}

/** The answer while it is still arriving. Citations become clickable once the answer is complete. */
export function PendingAnswer({ text, phase, engine }: PendingAnswerProps) {
  const searching = phase === "searching" && !text;
  return (
    <AssistantFrame busy>
      {searching ? (
        <div>
          <p className="flex items-center gap-2 text-sm font-medium text-fg-muted">
            <span className="flex gap-1" aria-hidden>
              <span className="size-1.5 animate-pulse-soft rounded-full bg-accent" />
              <span className="size-1.5 animate-pulse-soft rounded-full bg-accent [animation-delay:160ms]" />
              <span className="size-1.5 animate-pulse-soft rounded-full bg-accent [animation-delay:320ms]" />
            </span>
            Searching the knowledge base
          </p>
          <div className="mt-3.5 max-w-[64ch] space-y-2.5">
            <Skeleton className="h-3.5 w-full" />
            <Skeleton className="h-3.5 w-11/12" />
            <Skeleton className="h-3.5 w-3/5" />
          </div>
        </div>
      ) : (
        <AnswerText content={text} citations={[]} active={null} streaming />
      )}
      {engine && (
        <div className="mt-3 flex min-h-8 items-center">
          <EngineChip engine={engine.name} label={engine.label} size="sm" />
        </div>
      )}
    </AssistantFrame>
  );
}
