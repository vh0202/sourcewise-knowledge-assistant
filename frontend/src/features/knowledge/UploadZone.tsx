import { Check, CircleAlert, X } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";

import { UploadArt } from "../../components/illustrations";
import { Button, FileTypeIcon, IconButton, SELECT_CLASS } from "../../components/ui";
import { api, ApiError } from "../../lib/api";
import { classNames, formatBytes, formatPercent } from "../../lib/format";
import type { Collection, KbDocument } from "../../lib/types";
import { isProcessing, PipelineTrack } from "./Pipeline";

const ACCEPT = ".md,.markdown,.txt,.pdf,.html,.htm";

interface Upload {
  key: string;
  name: string;
  size: number;
  kind: string;
  state: "waiting" | "uploading" | "done" | "error";
  /** Share of the file that has been sent, 0 to 1. */
  progress: number;
  /** The document the server created; its pipeline is shown once the file has arrived. */
  documentId?: number;
  message?: string;
}

interface UploadZoneProps {
  collections: Collection[];
  /** The current documents, used to show the pipeline of each uploaded file. */
  documents: KbDocument[];
  targetId: number | null;
  onTargetChange: (collectionId: number) => void;
  onUploaded: () => void;
}

function kindOf(filename: string): string {
  const extension = filename.split(".").pop()?.toLowerCase() ?? "";
  if (extension === "markdown") return "md";
  if (extension === "htm") return "html";
  return extension;
}

/**
 * Drag-and-drop (or browse) upload into a collection. Files are sent one after another; each
 * shows how much has been sent, and then the ingestion pipeline of the document it became.
 */
export function UploadZone({ collections, documents, targetId, onTargetChange, onUploaded }: UploadZoneProps) {
  const input = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  const [dragging, setDragging] = useState(false);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const busy = uploads.some((upload) => upload.state === "uploading" || upload.state === "waiting");

  const patch = (key: string, change: Partial<Upload>) =>
    setUploads((current) => current.map((upload) => (upload.key === key ? { ...upload, ...change } : upload)));

  const upload = async (files: File[]) => {
    if (targetId == null || files.length === 0 || busy) return;
    const batch = files.map<Upload>((file, index) => ({
      key: `${Date.now()}-${index}-${file.name}`,
      name: file.name,
      size: file.size,
      kind: kindOf(file.name),
      state: "waiting",
      progress: 0,
    }));
    setUploads(batch);
    for (const [index, file] of files.entries()) {
      const key = batch[index]?.key;
      if (!key) continue;
      patch(key, { state: "uploading" });
      try {
        const document = await api.uploadDocument(targetId, file, (progress) => patch(key, { progress }));
        patch(key, { state: "done", progress: 1, documentId: document.id });
      } catch (error) {
        patch(key, { state: "error", message: error instanceof ApiError ? error.message : "Upload failed." });
      }
      onUploaded();
    }
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    void upload(Array.from(event.dataTransfer.files));
  };

  return (
    <div>
      <div
        onDragEnter={(event) => {
          event.preventDefault();
          dragDepth.current += 1;
          setDragging(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => {
          dragDepth.current = Math.max(0, dragDepth.current - 1);
          if (dragDepth.current === 0) setDragging(false);
        }}
        onDrop={onDrop}
        className={classNames(
          "flex flex-col items-center gap-x-5 gap-y-4 rounded-xl border border-dashed px-5 py-5 text-center transition-[border-color,background-color,box-shadow] duration-200 ease-standard sm:flex-row sm:text-left",
          dragging ? "border-accent bg-accent-soft shadow-[0_0_0_4px_var(--accent-soft-strong)]" : "border-line-strong bg-sunken",
        )}
      >
        {/* Between the phone layout (stacked) and wide screens there is no room for the picture beside the text. */}
        <UploadArt className={classNames("h-[4.5rem] w-24 transition-transform duration-200 ease-out sm:hidden xl:block", dragging && "-translate-y-1 scale-105")} />
        <div className="min-w-0 flex-1">
          <p className="text-base font-semibold text-fg">{dragging ? "Drop to upload" : "Drop documents here, or browse"}</p>
          <p className="mt-0.5 text-sm text-fg-muted">
            Markdown, plain text, HTML or PDF, up to 10 MB each. Every file is parsed, normalised, chunked and indexed.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-center gap-2">
          <label className="flex items-center gap-2 text-sm text-fg-muted">
            <span>Into</span>
            <select
              aria-label="Collection to upload into"
              value={targetId ?? ""}
              onChange={(event) => onTargetChange(Number(event.target.value))}
              disabled={collections.length === 0}
              className={classNames(SELECT_CLASS, "h-8 max-w-48")}
            >
              {collections.length === 0 && <option value="">No collections</option>}
              {collections.map((collection) => (
                <option key={collection.id} value={collection.id}>
                  {collection.name}
                </option>
              ))}
            </select>
          </label>
          <Button variant="primary" loading={busy} disabled={targetId == null} onClick={() => input.current?.click()}>
            Browse files
          </Button>
          <input
            ref={input}
            type="file"
            multiple
            accept={ACCEPT}
            className="sr-only"
            tabIndex={-1}
            aria-label="Choose documents to upload"
            onChange={(event) => {
              void upload(Array.from(event.target.files ?? []));
              event.target.value = "";
            }}
          />
        </div>
      </div>

      {uploads.length > 0 && (
        <div className="mt-3 overflow-hidden rounded-xl border border-line bg-card shadow-xs">
          <div className="flex items-center justify-between gap-3 border-b border-line-faint py-1.5 pr-2 pl-4">
            <p className="text-xs font-medium text-fg-muted" aria-live="polite">
              {busy
                ? `Uploading ${uploads.filter((item) => item.state === "done" || item.state === "error").length + 1} of ${uploads.length}`
                : `${uploads.filter((item) => item.state === "done").length} of ${uploads.length} uploaded`}
            </p>
            <IconButton size="sm" label="Clear the upload list" disabled={busy} onClick={() => setUploads([])}>
              <X className="size-3.5" aria-hidden />
            </IconButton>
          </div>
          <ul className="divide-y divide-line-faint">
            {uploads.map((item) => {
              const document = item.documentId != null ? documents.find((candidate) => candidate.id === item.documentId) : undefined;
              return (
                <li key={item.key} className="flex items-center gap-3 px-4 py-2.5">
                  <FileTypeIcon kind={item.kind} size="sm" />
                  <div className="min-w-0 flex-1">
                    <p className="flex items-baseline gap-2 text-sm">
                      <span className="truncate font-medium text-fg">{item.name}</span>
                      <span className="shrink-0 text-xs text-fg-subtle tabular-nums">{formatBytes(item.size)}</span>
                    </p>
                    {item.state === "error" ? (
                      <p className="mt-0.5 text-xs text-danger-fg">{item.message}</p>
                    ) : item.state === "done" ? (
                      <p className="mt-0.5 text-xs text-fg-muted">
                        {document == null
                          ? "Uploaded"
                          : document.status === "failed"
                            ? "Uploaded, but ingestion failed"
                            : isProcessing(document)
                              ? "Uploaded. Running the ingestion pipeline"
                              : `Indexed as ${document.chunk_count} ${document.chunk_count === 1 ? "chunk" : "chunks"}`}
                      </p>
                    ) : (
                      <div
                        role="progressbar"
                        aria-label={`Uploading ${item.name}`}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={Math.round(item.progress * 100)}
                        className="mt-1.5 h-1 overflow-hidden rounded-full bg-series-1-soft"
                      >
                        <div className="h-full rounded-full bg-accent transition-[width] duration-200 ease-standard" style={{ width: `${item.progress * 100}%` }} />
                      </div>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    {item.state === "uploading" && <span className="text-xs font-medium text-fg-muted tabular-nums">{formatPercent(item.progress)}</span>}
                    {item.state === "waiting" && <span className="text-xs text-fg-subtle">Waiting</span>}
                    {item.state === "done" && document && <PipelineTrack document={document} />}
                    {item.state === "done" && !document && <Check className="size-4 text-success-fg" aria-hidden />}
                    {item.state === "error" && <CircleAlert className="size-4 text-danger-fg" aria-hidden />}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
