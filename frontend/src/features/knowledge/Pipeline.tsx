import { Check, CircleAlert, LoaderCircle, X } from "lucide-react";

import { Badge } from "../../components/ui";
import { classNames, formatDuration } from "../../lib/format";
import type { DocumentStatus, KbDocument, Stage } from "../../lib/types";

const STATUS_LABEL: Record<DocumentStatus, string> = {
  queued: "Queued",
  parsing: "Parsing",
  normalizing: "Normalising",
  chunking: "Chunking",
  indexing: "Indexing",
  ready: "Ready",
  failed: "Failed",
};

export function isProcessing(document: KbDocument): boolean {
  return document.status !== "ready" && document.status !== "failed";
}

export function StatusChip({ document }: { document: KbDocument }) {
  if (document.status === "ready") {
    return (
      <Badge tone="success" icon={<Check className="size-3" aria-hidden />}>
        Ready
      </Badge>
    );
  }
  if (document.status === "failed") {
    return (
      <Badge tone="danger" icon={<CircleAlert className="size-3" aria-hidden />}>
        Failed
      </Badge>
    );
  }
  return (
    <Badge tone="accent" icon={<LoaderCircle className="size-3 animate-spin" aria-hidden />}>
      {STATUS_LABEL[document.status]}
    </Badge>
  );
}

const STAGE_NAMES = [
  { name: "parse", label: "Parse" },
  { name: "normalize", label: "Normalise" },
  { name: "chunk", label: "Chunk" },
  { name: "index", label: "Index" },
];

function stagesOf(document: KbDocument): Stage[] {
  // A queued document has no stage records yet; show the four steps as pending.
  return STAGE_NAMES.map(
    ({ name, label }) =>
      document.stages.find((stage) => stage.name === name) ?? { name, label, status: "pending", duration_ms: null, detail: null },
  );
}

const STATE_WORD: Record<Stage["status"], string> = { done: "done", running: "in progress", failed: "failed", pending: "waiting" };

const NODE: Record<Stage["status"], string> = {
  done: "bg-success text-white",
  running: "bg-accent-soft-strong text-accent-fg ring-[1.5px] ring-accent ring-inset",
  failed: "bg-danger text-white",
  pending: "text-fg-subtle ring-[1.5px] ring-line-strong ring-inset",
};

/** The round marker of one stage: a tick, a spinner, a cross, or (not started) its number. */
function StageNode({ stage, index, large = false }: { stage: Stage; index: number; large?: boolean }) {
  const icon = large ? "size-3.5" : "size-2.5";
  return (
    // The outer disc is opaque so that the connecting line does not show through a tinted node.
    <span className="relative z-10 flex shrink-0 rounded-full bg-card">
      <span
        className={classNames(
          "flex items-center justify-center rounded-full font-semibold transition-colors duration-200 ease-standard",
          large ? "size-7 text-xs" : "size-4 text-[0.5625rem]",
          NODE[stage.status],
        )}
      >
        {stage.status === "done" ? (
          <Check className={icon} strokeWidth={3} aria-hidden />
        ) : stage.status === "failed" ? (
          <X className={icon} strokeWidth={3} aria-hidden />
        ) : stage.status === "running" ? (
          <LoaderCircle className={classNames(icon, "animate-spin")} strokeWidth={2.5} aria-hidden />
        ) : (
          index + 1
        )}
      </span>
    </span>
  );
}

/** The line between two stages is filled once the stage it leads to has started. */
function reached(stage: Stage | undefined): boolean {
  return stage != null && stage.status !== "pending";
}

/**
 * The ingestion pipeline of a document as four connected nodes (parse, normalise, chunk,
 * index), for the documents table. Each state has its own glyph, so it reads without colour.
 */
export function PipelineTrack({ document, labels = false }: { document: KbDocument; labels?: boolean }) {
  const stages = stagesOf(document);
  const summary = stages.map((stage) => `${stage.label} ${STATE_WORD[stage.status]}`).join(", ");
  return (
    // The negative margin puts the first node, not the empty half of its cell, on the column's left edge.
    <span role="img" aria-label={`Ingestion pipeline: ${summary}`} className={classNames("inline-flex items-start", labels ? "-ml-[1.375rem]" : "-ml-1.5")}>
      {stages.map((stage, index) => (
        <span key={stage.name} className={classNames("relative flex flex-col items-center", labels ? "w-[3.75rem]" : "w-7")}>
          {index > 0 && (
            <span
              aria-hidden
              className={classNames(
                "absolute top-[7px] right-1/2 h-0.5 w-full transition-colors duration-200 ease-standard",
                reached(stage) ? (stage.status === "failed" ? "bg-danger" : "bg-success") : "bg-line-strong",
              )}
            />
          )}
          <StageNode stage={stage} index={index} />
          {labels && (
            <span aria-hidden className={classNames("mt-1 text-2xs leading-3", stage.status === "pending" ? "text-fg-subtle" : "text-fg-muted")}>
              {stage.label}
            </span>
          )}
        </span>
      ))}
    </span>
  );
}

/** The pipeline laid out step by step with what each stage did and how long it took. */
export function PipelineSteps({ document }: { document: KbDocument }) {
  const stages = stagesOf(document);
  return (
    <ol className="flex flex-col sm:flex-row">
      {stages.map((stage, index) => (
        <li key={stage.name} className="flex min-w-0 gap-3 sm:flex-1 sm:flex-col sm:gap-0">
          {/* The node, then the connector to the next stage: a row on wide screens, a column on narrow ones. */}
          <div className="flex flex-col items-center sm:flex-row">
            <StageNode stage={stage} index={index} large />
            {index < stages.length - 1 && (
              <span
                aria-hidden
                className={classNames(
                  "w-0.5 flex-1 transition-colors duration-200 ease-standard sm:h-0.5 sm:w-auto",
                  reached(stages[index + 1]) ? "bg-success" : "bg-line-strong",
                )}
              />
            )}
          </div>
          <div className="min-w-0 pb-5 sm:mt-3 sm:pr-6 sm:pb-0">
            <p className="flex items-baseline gap-2">
              <span className="text-base font-semibold text-fg">{stage.label}</span>
              <span className="text-xs text-fg-subtle tabular-nums">
                {stage.status === "done" && stage.duration_ms != null
                  ? formatDuration(stage.duration_ms)
                  : stage.status === "running"
                    ? "In progress"
                    : stage.status === "failed"
                      ? "Failed"
                      : "Waiting"}
              </span>
            </p>
            {stage.detail && <p className="mt-1 text-sm text-fg-muted">{stage.detail}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}
