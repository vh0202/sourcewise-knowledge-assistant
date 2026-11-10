import { ChevronRight, Link2, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { Crumb, Page } from "../components/AppShell";
import { NoDataArt } from "../components/illustrations";
import { Modal, Tooltip } from "../components/overlays";
import { useToast } from "../components/toast";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorNotice, FileTypeIcon, fileKindName, Skeleton } from "../components/ui";
import { isProcessing, PipelineSteps, StatusChip } from "../features/knowledge/Pipeline";
import { api, ApiError } from "../lib/api";
import { classNames, formatBytes, formatDateTime, formatNumber, pageLabel, sectionLabel } from "../lib/format";
import { scrollBehavior } from "../lib/hooks";
import type { Chunk, DocumentChunks } from "../lib/types";

function message(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

// -- Outline -----------------------------------------------------------------------------------
/** Consecutive chunks under the same heading. Chunks never cross a heading, so this is the document's outline. */
interface Section {
  index: number;
  path: string[];
  chunks: Chunk[];
}

function sectionsOf(chunks: Chunk[]): Section[] {
  const sections: Section[] = [];
  for (const chunk of chunks) {
    const last = sections[sections.length - 1];
    if (last && last.path.join("\n") === chunk.heading_path.join("\n")) last.chunks.push(chunk);
    else sections.push({ index: sections.length, path: chunk.heading_path, chunks: [chunk] });
  }
  return sections;
}

/** A row of the outline: either a heading that only groups others, or a section that holds chunks. */
interface OutlineRow {
  key: string;
  label: string;
  depth: number;
  /** The section to jump to (for a grouping heading: its first sub-section). */
  section: Section;
  /** True when the row is the section itself rather than one of its parent headings. */
  own: boolean;
}

function outlineOf(sections: Section[]): OutlineRow[] {
  const rows: OutlineRow[] = [];
  let previous: string[] = [];
  for (const section of sections) {
    const path = section.path.length ? section.path : ["Introduction"];
    let shared = 0;
    while (shared < previous.length && shared < path.length - 1 && previous[shared] === path[shared]) shared += 1;
    for (let depth = shared; depth < path.length; depth += 1) {
      rows.push({ key: `${section.index}-${depth}`, label: path[depth] ?? "", depth, section, own: depth === path.length - 1 });
    }
    previous = path;
  }
  return rows;
}

/** One small block per chunk; a chunk that repeats the end of the previous one is linked to it. */
function ChunkPips({ chunks, active }: { chunks: Chunk[]; active: boolean }) {
  const fill = active ? "bg-series-1" : "bg-fg-faint";
  return (
    <span aria-hidden className="flex shrink-0 items-center">
      {chunks.map((chunk, index) => (
        <span key={chunk.id} className="flex items-center">
          {index > 0 && <span className={classNames("h-0.5", chunk.overlap_chars > 0 ? classNames("w-1.5", fill) : "w-1")} />}
          <span className={classNames("size-2 rounded-[2px] transition-colors duration-150", fill)} />
        </span>
      ))}
    </span>
  );
}

function Outline({ rows, activeSection, onSelect }: { rows: OutlineRow[]; activeSection: number | null; onSelect: (section: Section) => void }) {
  return (
    <nav aria-label="Document outline">
      <ul className="space-y-px">
        {rows.map((row) => {
          const active = row.own && row.section.index === activeSection;
          const overlaps = row.section.chunks.filter((chunk) => chunk.overlap_chars > 0).length;
          return (
            <li key={row.key}>
              <button
                type="button"
                onClick={() => onSelect(row.section)}
                aria-current={active ? "location" : undefined}
                aria-label={
                  row.own
                    ? `${row.label}: ${row.section.chunks.length} ${row.section.chunks.length === 1 ? "chunk" : "chunks"}${overlaps ? `, ${overlaps} sharing text with the one before` : ""}`
                    : row.label
                }
                style={{ paddingLeft: `${0.625 + row.depth * 0.75}rem` }}
                className={classNames(
                  "relative flex min-h-7 w-full items-center gap-2 rounded-md py-1 pr-2 text-left text-sm transition-colors duration-150 ease-standard",
                  active ? "bg-accent-soft font-medium text-accent-fg" : row.own ? "text-fg-muted hover:bg-wash hover:text-fg" : "font-medium text-fg hover:bg-wash",
                )}
              >
                {active && <span aria-hidden className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-accent" />}
                <span className="min-w-0 flex-1 truncate">{row.label}</span>
                {row.own && <ChunkPips chunks={row.section.chunks} active={active} />}
              </button>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 flex items-center gap-2 border-t border-line-faint px-2.5 pt-3 text-xs text-fg-subtle">
        <span aria-hidden className="flex shrink-0 items-center">
          <span className="size-2 rounded-[2px] bg-fg-faint" />
          <span className="h-0.5 w-1.5 bg-fg-faint" />
          <span className="size-2 rounded-[2px] bg-fg-faint" />
        </span>
        Linked blocks share text
      </p>
    </nav>
  );
}

// -- Document map ------------------------------------------------------------------------------
/**
 * The whole document as one strip: a block per chunk, sized by its length, grouped under the
 * top-level heading it belongs to. The hatched part of a block is text it shares with the
 * previous chunk.
 */
function DocumentMap({ chunks, activeId, onSelect }: { chunks: Chunk[]; activeId: number | null; onSelect: (chunk: Chunk) => void }) {
  const groups = useMemo(() => {
    const result: { label: string; chunks: Chunk[]; length: number }[] = [];
    for (const chunk of chunks) {
      const label = chunk.heading_path[0] ?? "Introduction";
      const length = chunk.end_char - chunk.start_char;
      const last = result[result.length - 1];
      if (last && last.label === label) {
        last.chunks.push(chunk);
        last.length += length;
      } else result.push({ label, chunks: [chunk], length });
    }
    return result;
  }, [chunks]);

  const total = groups.reduce((sum, group) => sum + group.length, 0) || 1;

  return (
    <div className="flex w-full gap-0.5" role="list" aria-label="Chunks in document order, grouped by top-level heading">
      {groups.map((group, groupIndex) => (
        <div key={`${groupIndex}-${group.label}`} style={{ flexGrow: group.length, flexBasis: 0 }} className="min-w-2">
          <div className="flex h-8 gap-0.5">
            {group.chunks.map((chunk) => {
              const length = chunk.end_char - chunk.start_char;
              const label = `Chunk ${chunk.ordinal + 1} · ${sectionLabel(chunk.heading_path)} · ${formatNumber(length)} characters${
                chunk.overlap_chars ? ` · ${chunk.overlap_chars} shared with the previous chunk` : ""
              }`;
              return (
                <Tooltip key={chunk.id} label={label}>
                  <button
                    type="button"
                    role="listitem"
                    onClick={() => onSelect(chunk)}
                    aria-label={`Go to chunk ${chunk.ordinal + 1}: ${sectionLabel(chunk.heading_path)}`}
                    style={{ flexGrow: length, flexBasis: 0 }}
                    className={classNames(
                      "relative min-w-1 overflow-hidden rounded-[3px] transition-[background-color,opacity] duration-150 ease-standard hover:opacity-100",
                      chunk.id === activeId ? "bg-accent-strong" : "bg-series-1 opacity-80",
                    )}
                  >
                    {chunk.overlap_chars > 0 && (
                      <span aria-hidden className="overlap-hatch absolute inset-y-0 left-0" style={{ width: `${Math.min(100, (chunk.overlap_chars / length) * 100)}%` }} />
                    )}
                  </button>
                </Tooltip>
              );
            })}
          </div>
          {/* The heading the chunks above belong to; named only where there is room for a name. */}
          <div aria-hidden className="mt-1.5 h-5 border-t border-line-strong pt-1">
            {group.length / total >= 0.085 && <p className="truncate text-2xs text-fg-subtle">{group.label}</p>}
          </div>
        </div>
      ))}
    </div>
  );
}

// -- Chunks ------------------------------------------------------------------------------------
type Highlight = { id: number; from: "citation" | "map" } | null;

function ChunkCard({ chunk, highlight }: { chunk: Chunk; highlight: Highlight }) {
  const overlap = chunk.text.slice(0, chunk.overlap_chars);
  const rest = chunk.text.slice(chunk.overlap_chars);
  const page = pageLabel(chunk.page_start, chunk.page_end);
  const highlighted = highlight?.id === chunk.id;
  return (
    <li id={`chunk-${chunk.id}`} data-chunk={chunk.id} className={classNames("scroll-mt-20", chunk.overlap_chars === 0 && "mt-3 first:mt-0")}>
      {/* Where two chunks share text, they are visibly tied together. */}
      {chunk.overlap_chars > 0 && (
        <div className="relative flex h-9 items-center justify-center" aria-hidden>
          <span className="absolute inset-y-0 left-7 w-px bg-accent-line" />
          <span className="absolute inset-y-0 right-7 w-px bg-accent-line" />
          <span className="relative inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-2.5 py-0.5 text-xs font-medium text-accent-fg ring-1 ring-accent-line ring-inset">
            <Link2 className="size-3" />
            {chunk.overlap_chars} characters repeated from chunk {chunk.ordinal}
          </span>
        </div>
      )}
      <article
        className={classNames(
          "rounded-xl border bg-card transition-[border-color,box-shadow] duration-200 ease-standard",
          highlighted
            ? highlight.from === "citation"
              ? "border-cite-line shadow-[0_0_0_4px_var(--cite)]"
              : "border-accent-line shadow-[0_0_0_4px_var(--accent-soft-strong)]"
            : "border-line shadow-xs",
        )}
      >
        <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line-faint px-4 py-2.5">
          <span className="flex h-6 min-w-6 items-center justify-center rounded-sm bg-inverse px-1.5 text-xs font-semibold text-fg-inverse tabular-nums">
            {chunk.ordinal + 1}
          </span>
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-fg">{sectionLabel(chunk.heading_path)}</span>
          <span className="flex w-full shrink-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-subtle tabular-nums sm:w-auto">
            {page && <Badge>{page}</Badge>}
            <span>{formatNumber(chunk.text.length)} chars</span>
            <span>~{formatNumber(chunk.token_estimate)} tokens</span>
            <Tooltip label="Position in the normalised document text">
              <span>
                {formatNumber(chunk.start_char)}&ndash;{formatNumber(chunk.end_char)}
              </span>
            </Tooltip>
            {chunk.overlap_chars > 0 && <Badge tone="accent">{chunk.overlap_chars} overlap</Badge>}
          </span>
        </header>
        <p className="max-w-[78ch] px-4 py-3.5 text-base leading-7 whitespace-pre-wrap text-fg [text-wrap:pretty]">
          {overlap && <span className="overlap-text">{overlap}</span>}
          {rest}
        </p>
      </article>
    </li>
  );
}

function DocumentSkeleton() {
  return (
    <Page title="Document" breadcrumb={<Skeleton className="h-4 w-56" />}>
      <div role="status" aria-label="Loading document" className="space-y-6">
        <Skeleton className="h-[4.75rem] w-full rounded-xl" />
        <Skeleton className="h-44 w-full rounded-xl" />
        <Skeleton className="h-40 w-full rounded-xl" />
      </div>
    </Page>
  );
}

export function DocumentPage() {
  const params = useParams();
  const documentId = Number(params.documentId);
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();
  const [data, setData] = useState<DocumentChunks | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [working, setWorking] = useState(false);
  const [highlight, setHighlight] = useState<Highlight>(null);
  /** The chunk nearest the top of the viewport; it selects the active entry of the outline. */
  const [visibleId, setVisibleId] = useState<number | null>(null);
  const list = useRef<HTMLOListElement>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.documentChunks(documentId));
      setError(null);
    } catch (caught) {
      setError(message(caught, "The document could not be loaded."));
    }
  }, [documentId]);

  useEffect(() => {
    setData(null);
    void load();
  }, [load]);

  const processing = data ? isProcessing(data.document) : false;
  useEffect(() => {
    if (!processing) return;
    const timer = window.setInterval(() => void load(), 900);
    return () => window.clearInterval(timer);
  }, [processing, load]);

  const focusChunk = useCallback((chunkId: number, from: "citation" | "map") => {
    setHighlight({ id: chunkId, from });
    document.getElementById(`chunk-${chunkId}`)?.scrollIntoView({ block: from === "citation" ? "center" : "start", behavior: scrollBehavior() });
  }, []);

  // Arriving from a citation ("#chunk-42"): bring that chunk into view.
  const chunkCount = data?.chunks.length ?? 0;
  useEffect(() => {
    const match = /^#chunk-(\d+)$/.exec(location.hash);
    if (match && chunkCount > 0) focusChunk(Number(match[1]), "citation");
  }, [location.hash, chunkCount, focusChunk]);

  // Follow the reading position: the chunk that crosses a line a third of the way down the viewport.
  useEffect(() => {
    const element = list.current;
    if (!element || chunkCount === 0) return;
    const inView = new Set<number>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = Number((entry.target as HTMLElement).dataset.chunk);
          if (entry.isIntersecting) inView.add(id);
          else inView.delete(id);
        }
        const first = Array.from(element.querySelectorAll<HTMLElement>("[data-chunk]")).find((item) => inView.has(Number(item.dataset.chunk)));
        if (first) setVisibleId(Number(first.dataset.chunk));
      },
      { rootMargin: "-33% 0px -66% 0px" },
    );
    element.querySelectorAll("[data-chunk]").forEach((item) => observer.observe(item));
    return () => observer.disconnect();
  }, [chunkCount]);

  const sections = useMemo(() => sectionsOf(data?.chunks ?? []), [data]);
  const outline = useMemo(() => outlineOf(sections), [sections]);

  if (error && !data) {
    return (
      <Page title="Document" breadcrumb={<Crumb to="/knowledge">Knowledge base</Crumb>}>
        <ErrorNotice message={error} onRetry={() => void load()} />
      </Page>
    );
  }
  if (!data) return <DocumentSkeleton />;

  const { document: doc, chunks, chunking } = data;
  const overlapping = chunks.filter((chunk) => chunk.overlap_chars > 0).length;
  const average = chunks.length ? Math.round(chunks.reduce((sum, chunk) => sum + chunk.text.length, 0) / chunks.length) : 0;
  const activeSection = sections.find((section) => section.chunks.some((chunk) => chunk.id === (visibleId ?? chunks[0]?.id)))?.index ?? null;

  const reindex = async () => {
    setWorking(true);
    setActionError(null);
    try {
      await api.reindexDocument(doc.id);
      toast({ title: "Re-indexing started" });
      await load();
    } catch (caught) {
      setActionError(message(caught, "The document could not be re-indexed."));
    } finally {
      setWorking(false);
    }
  };

  const remove = async () => {
    setWorking(true);
    try {
      await api.deleteDocument(doc.id);
      toast({ title: "Document deleted" });
      navigate("/knowledge");
    } catch (caught) {
      setActionError(message(caught, "The document could not be deleted."));
      setConfirmDelete(false);
      setWorking(false);
    }
  };

  const facts = [
    { label: "File", value: doc.filename },
    { label: "Size", value: formatBytes(doc.size_bytes) },
    ...(doc.page_count != null ? [{ label: "Pages", value: formatNumber(doc.page_count) }] : []),
    { label: "Characters", value: formatNumber(doc.char_count) },
    { label: "Chunks", value: formatNumber(doc.chunk_count) },
    { label: "Indexed", value: doc.indexed_at ? formatDateTime(doc.indexed_at) : "–" },
  ];

  return (
    <Page
      title={doc.title}
      leading={<FileTypeIcon kind={doc.kind} size="lg" className="mt-0.5 hidden sm:block" />}
      breadcrumb={
        <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-sm whitespace-nowrap">
          <Crumb to="/knowledge">Knowledge base</Crumb>
          <ChevronRight className="size-3.5 shrink-0 text-fg-faint" aria-hidden />
          <span className="hidden truncate text-fg-muted sm:inline">{doc.collection_name}</span>
          <ChevronRight className="hidden size-3.5 shrink-0 text-fg-faint sm:inline" aria-hidden />
          <span className="truncate font-medium text-fg">Chunk inspector</span>
        </nav>
      }
      description={
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1.5 text-sm">
          <StatusChip document={doc} />
          <span>
            {fileKindName(doc.kind)} in {doc.collection_name}
          </span>
        </span>
      }
      actions={
        <>
          <Button icon={<RefreshCw className="size-4" aria-hidden />} loading={working && !confirmDelete} disabled={processing} onClick={() => void reindex()}>
            Re-index
          </Button>
          <Button icon={<Trash2 className="size-4" aria-hidden />} onClick={() => setConfirmDelete(true)}>
            Delete
          </Button>
        </>
      }
    >
      {actionError && <ErrorNotice message={actionError} className="mb-4" />}
      {doc.status === "failed" && doc.error && <ErrorNotice message={`Ingestion failed: ${doc.error}`} className="mb-4" />}

      <Card className="overflow-hidden">
        {/* Below the `lg` breakpoint the facts wrap into a grid; the last row's rule is tucked under the card's edge. */}
        <dl className="grid grid-cols-2 max-lg:-mb-px sm:grid-cols-3 lg:flex">
          {facts.map((fact) => (
            <div key={fact.label} className="min-w-0 border-line-faint px-5 py-3.5 max-lg:border-b lg:flex-1 lg:border-r lg:last:border-r-0">
              <dt className="text-xs text-fg-subtle">{fact.label}</dt>
              <dd className="mt-0.5 truncate text-sm font-semibold text-fg tabular-nums" title={fact.value}>
                {fact.value}
              </dd>
            </div>
          ))}
        </dl>
      </Card>

      <Card className="mt-6">
        <CardHeader title="Ingestion pipeline" description="What each stage did the last time this document was processed." />
        <div className="px-5 pt-2 pb-5">
          <PipelineSteps document={doc} />
        </div>
      </Card>

      <Card className="mt-6">
        <CardHeader
          title="How the document was split"
          description={
            <>
              Chunks never cross a heading. Within a section, whole sentences are packed up to {formatNumber(chunking.max_chars)}{" "}
              characters, and each chunk starts with up to {chunking.overlap_chars} characters from the end of the one before.
            </>
          }
        />
        <div className="px-5 pt-2 pb-5">
          {chunks.length > 0 ? (
            <>
              <DocumentMap chunks={chunks} activeId={highlight?.id ?? null} onSelect={(chunk) => focusChunk(chunk.id, "map")} />
              <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-fg-muted">
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-3 w-4 rounded-[3px] bg-series-1" aria-hidden />
                  One block per chunk, sized by length
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="overlap-hatch h-3 w-4 rounded-[3px] bg-series-1" aria-hidden />
                  Text shared with the previous chunk
                </span>
                <span className="ml-auto tabular-nums">
                  {formatNumber(chunks.length)} chunks &middot; average {formatNumber(average)} characters &middot; {overlapping} with overlap
                </span>
              </div>
            </>
          ) : (
            <p className="text-sm text-fg-muted">{processing ? "The document is still being processed." : "No chunks were produced."}</p>
          )}
        </div>
      </Card>

      {chunks.length === 0 ? (
        <Card className="mt-6">
          <EmptyState illustration={<NoDataArt />} title="No chunks to show">
            {processing ? "They will appear here when ingestion finishes." : "Re-index the document after fixing the problem above."}
          </EmptyState>
        </Card>
      ) : (
        <div className="mt-8 grid gap-x-8 gap-y-6 lg:grid-cols-[14.5rem_minmax(0,1fr)]">
          <aside className="hidden self-start lg:sticky lg:top-[4.75rem] lg:block">
            <h2 className="px-2.5 text-2xs font-medium tracking-caps text-fg-subtle uppercase">Outline</h2>
            <div className="mt-2 max-h-[calc(100dvh-11rem)] overflow-y-auto">
              <Outline rows={outline} activeSection={activeSection} onSelect={(section) => section.chunks[0] && focusChunk(section.chunks[0].id, "map")} />
            </div>
          </aside>

          <section aria-labelledby="chunks-heading" className="min-w-0">
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <h2 id="chunks-heading" className="text-base font-semibold text-fg">
                Chunks
              </h2>
              <p className="text-sm text-fg-muted">In document order. Hatched text also ends the chunk before it.</p>
            </div>
            <ol ref={list} className="mt-3">
              {chunks.map((chunk) => (
                <ChunkCard key={chunk.id} chunk={chunk} highlight={highlight} />
              ))}
            </ol>
          </section>
        </div>
      )}

      {confirmDelete && (
        <Modal
          title="Delete document?"
          description={`“${doc.title}”, its ${doc.chunk_count} chunks and its index entries will be removed. Past answers keep the passages they cited.`}
          onClose={() => setConfirmDelete(false)}
          footer={
            <>
              <Button onClick={() => setConfirmDelete(false)}>Cancel</Button>
              <Button variant="danger" loading={working} onClick={() => void remove()}>
                Delete document
              </Button>
            </>
          }
        />
      )}
    </Page>
  );
}
