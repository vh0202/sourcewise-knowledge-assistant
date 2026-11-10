import { Ellipsis, FolderPlus, Layers, Pencil, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Page } from "../components/AppShell";
import { UploadArt } from "../components/illustrations";
import { Menu, MenuItem, Modal, Tooltip } from "../components/overlays";
import { useToast } from "../components/toast";
import { Button, Card, EmptyState, ErrorNotice, Field, FileTypeIcon, IconButton, INPUT_CLASS, Skeleton, Tabs } from "../components/ui";
import { isProcessing, PipelineTrack, StatusChip } from "../features/knowledge/Pipeline";
import { UploadZone } from "../features/knowledge/UploadZone";
import { api, ApiError } from "../lib/api";
import { classNames, formatBytes, formatNumber, formatRelative } from "../lib/format";
import { useCountUp } from "../lib/hooks";
import { useSession } from "../lib/session";
import type { Collection, KbDocument } from "../lib/types";

type Dialog =
  | { kind: "collection"; collection: Collection | null }
  | { kind: "delete-collection"; collection: Collection }
  | { kind: "delete-document"; document: KbDocument };

const ALL = "all";

function message(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function CollectionForm({ collection, onClose, onSaved }: { collection: Collection | null; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(collection?.name ?? "");
  const [description, setDescription] = useState(collection?.description ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      if (collection) await api.updateCollection(collection.id, name, description);
      else await api.createCollection(name, description);
      onSaved();
    } catch (caught) {
      setError(message(caught, "The collection could not be saved."));
      setSaving(false);
    }
  };

  return (
    <Modal
      title={collection ? "Edit collection" : "New collection"}
      description="A collection groups related documents. People can limit a question to one collection."
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="collection-form" loading={saving} disabled={!name.trim()}>
            {collection ? "Save changes" : "Create collection"}
          </Button>
        </>
      }
    >
      <form id="collection-form" onSubmit={submit} className="space-y-4">
        {error && <ErrorNotice message={error} />}
        <Field label="Name">
          {(id) => (
            <input id={id} autoFocus required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} className={INPUT_CLASS} placeholder="e.g. Finance policies" />
          )}
        </Field>
        <Field label="Description" hint="Optional. Shown to administrators only.">
          {(id) => (
            <textarea id={id} rows={3} maxLength={500} value={description} onChange={(event) => setDescription(event.target.value)} className={INPUT_CLASS} />
          )}
        </Field>
      </form>
    </Modal>
  );
}

/** A number that counts up to its value when it first appears. */
function CountUp({ value }: { value: number }) {
  return <>{formatNumber(Math.round(useCountUp(value)))}</>;
}

function KnowledgeSkeleton() {
  return (
    <Page title="Knowledge base">
      <div role="status" aria-label="Loading the knowledge base">
        <Skeleton className="h-[5.25rem] w-full rounded-xl" />
        <Skeleton className="mt-6 h-28 w-full rounded-xl" />
        <div className="mt-6 space-y-3 rounded-xl border border-line bg-card p-5">
          {[0, 1, 2, 3, 4].map((row) => (
            <div key={row} className="flex items-center gap-4">
              <Skeleton className="h-9 w-7" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-3.5 w-2/5" />
                <Skeleton className="h-3 w-1/4" />
              </div>
              <Skeleton className="h-4 w-28" />
            </div>
          ))}
        </div>
      </div>
    </Page>
  );
}

const TH = "sticky top-14 z-10 border-b border-line bg-card/95 py-2.5 text-2xs font-medium tracking-caps whitespace-nowrap text-fg-subtle uppercase backdrop-blur-sm";

export function KnowledgePage() {
  const { meta } = useSession();
  const toast = useToast();
  const navigate = useNavigate();
  const [collections, setCollections] = useState<Collection[] | null>(null);
  const [documents, setDocuments] = useState<KbDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null); // null = all documents
  const [targetId, setTargetId] = useState<number | null>(null);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [working, setWorking] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [nextCollections, nextDocuments] = await Promise.all([api.collections(), api.documents()]);
      setCollections(nextCollections);
      setDocuments(nextDocuments);
      setError(null);
    } catch (caught) {
      setError(message(caught, "The knowledge base could not be loaded."));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // While anything is still being ingested, poll so that the pipeline status stays live.
  const processing = documents?.some(isProcessing) ?? false;
  useEffect(() => {
    if (!processing) return;
    const timer = window.setInterval(() => void refresh(), 900);
    return () => window.clearInterval(timer);
  }, [processing, refresh]);

  // Upload into the selected collection, or the first one when "All documents" is selected.
  useEffect(() => {
    if (!collections?.length) return setTargetId(null);
    setTargetId((current) => selectedId ?? (collections.some((c) => c.id === current) ? current : (collections[0]?.id ?? null)));
  }, [collections, selectedId]);

  const visible = useMemo(
    () => (documents ?? []).filter((document) => selectedId == null || document.collection_id === selectedId),
    [documents, selectedId],
  );
  const selected = collections?.find((collection) => collection.id === selectedId) ?? null;
  const totalChunks = (collections ?? []).reduce((sum, collection) => sum + collection.chunk_count, 0);

  const run = async (action: () => Promise<unknown>, fallback: string, done: string) => {
    setWorking(true);
    setActionError(null);
    try {
      await action();
      setDialog(null);
      toast({ title: done });
      await refresh();
    } catch (caught) {
      setActionError(message(caught, fallback));
      setDialog(null);
    } finally {
      setWorking(false);
    }
  };

  if (error && !documents) {
    return (
      <Page title="Knowledge base">
        <ErrorNotice message={error} onRetry={() => void refresh()} />
      </Page>
    );
  }
  if (!collections || !documents) return <KnowledgeSkeleton />;

  return (
    <Page
      title="Knowledge base"
      description="The documents the assistant answers from. Upload a file to run it through the ingestion pipeline, then inspect how it was split into chunks."
      actions={
        <Button icon={<FolderPlus className="size-4" aria-hidden />} onClick={() => setDialog({ kind: "collection", collection: null })}>
          New collection
        </Button>
      }
    >
      <Card>
        {/* Two by two on a phone, one row of four from the `sm` breakpoint. */}
        <dl className="grid grid-cols-2 sm:grid-cols-[1fr_1fr_1fr_1.5fr]">
          {[
            { label: "Collections", value: <CountUp value={collections.length} /> },
            { label: "Documents", value: <CountUp value={documents.length} /> },
            { label: "Chunks indexed", value: <CountUp value={totalChunks} /> },
            { label: "Retrieval", value: meta?.retriever.label ?? "–", text: true },
          ].map((stat, index) => (
            <div
              key={stat.label}
              className={classNames(
                "border-line-faint px-5 py-4 sm:border-r sm:last:border-r-0",
                index % 2 === 0 && "border-r",
                index < 2 && "border-b sm:border-b-0",
              )}
            >
              <dt className="text-sm text-fg-muted">{stat.label}</dt>
              <dd className={classNames("mt-1 font-semibold text-fg", stat.text ? "text-base leading-8" : "text-2xl tracking-tight")}>{stat.value}</dd>
            </div>
          ))}
        </dl>
      </Card>

      {actionError && <ErrorNotice message={actionError} className="mt-4" />}

      <div className="mt-6">
        <UploadZone collections={collections} documents={documents} targetId={targetId} onTargetChange={setTargetId} onUploaded={() => void refresh()} />
      </div>

      <Card className="mt-6 min-w-0">
        <div className="flex items-center gap-2 border-b border-line pr-3 pl-2.5">
          <div className="min-w-0 flex-1 overflow-x-auto">
            <Tabs
              label="Collections"
              controls="documents-panel"
              value={selectedId ?? ALL}
              onChange={(value) => setSelectedId(value === ALL ? null : Number(value))}
              options={[
                { value: ALL, label: "All documents", count: documents.length },
                ...collections.map((collection) => ({ value: collection.id, label: collection.name, count: collection.document_count })),
              ]}
            />
          </div>
          {selected && (
            <Menu
              label={`Actions for ${selected.name}`}
              trigger={(props) => (
                <IconButton label="Collection actions" {...props}>
                  <Ellipsis className="size-4" aria-hidden />
                </IconButton>
              )}
            >
              <MenuItem icon={<Pencil className="size-3.5" aria-hidden />} onSelect={() => setDialog({ kind: "collection", collection: selected })}>
                Edit collection
              </MenuItem>
              <MenuItem icon={<Trash2 className="size-3.5" aria-hidden />} danger onSelect={() => setDialog({ kind: "delete-collection", collection: selected })}>
                Delete collection
              </MenuItem>
            </Menu>
          )}
        </div>

        <div id="documents-panel" role="tabpanel" aria-label={selected ? selected.name : "All documents"}>
          {selected && <p className="border-b border-line-faint px-5 py-2.5 text-sm text-fg-muted">{selected.description || "No description."}</p>}

          {visible.length === 0 ? (
            <EmptyState illustration={<UploadArt />} title="No documents here yet">
              Upload a Markdown, text, HTML or PDF file above and it will appear here as soon as it has been indexed.
            </EmptyState>
          ) : (
            <table className="w-full border-separate border-spacing-0 text-left text-sm">
              <thead>
                <tr>
                  <th scope="col" className={classNames(TH, "w-full pr-3 pl-5")}>
                    Document
                  </th>
                  <th scope="col" className={classNames(TH, "hidden px-3 md:table-cell")}>
                    Pipeline
                  </th>
                  <th scope="col" className={classNames(TH, "hidden px-3 md:table-cell")}>
                    Status
                  </th>
                  <th scope="col" className={classNames(TH, "hidden px-3 text-right xl:table-cell")}>
                    Chunks
                  </th>
                  <th scope="col" className={classNames(TH, "hidden px-3 xl:table-cell")}>
                    Indexed
                  </th>
                  <th scope="col" className={classNames(TH, "pr-5 pl-3 text-right")}>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visible.map((document, index) => {
                  const last = index === visible.length - 1;
                  const cell = classNames("border-line-faint align-middle transition-colors duration-150 ease-standard group-hover/row:bg-wash", !last && "border-b");
                  return (
                    <tr key={document.id} className="group/row">
                      {/* max-w-0 lets the long text in this cell truncate instead of widening the table */}
                      <td className={classNames(cell, "w-full max-w-0 py-3 pr-3 pl-5", last && "rounded-bl-xl")}>
                        <div className="flex items-center gap-3.5">
                          <FileTypeIcon kind={document.kind} />
                          <div className="min-w-0 flex-1">
                            <Link
                              to={`/knowledge/documents/${document.id}`}
                              className="line-clamp-2 rounded-xs text-sm font-medium text-fg transition-colors duration-150 hover:text-accent-fg sm:block sm:truncate"
                            >
                              {document.title}
                            </Link>
                            <p className="mt-0.5 truncate text-xs text-fg-subtle">
                              {document.filename} &middot; {formatBytes(document.size_bytes)}
                              {document.chunk_count > 0 && (
                                <span className="xl:hidden">
                                  {" "}
                                  &middot; {document.chunk_count} chunks
                                </span>
                              )}
                              {document.page_count != null && (
                                <span>
                                  {" "}
                                  &middot; {document.page_count} {document.page_count === 1 ? "page" : "pages"}
                                </span>
                              )}
                              {selectedId == null && <span> &middot; {document.collection_name}</span>}
                            </p>
                            {document.status === "failed" && document.error && (
                              <p className="mt-1 text-xs whitespace-normal text-danger-fg">{document.error}</p>
                            )}
                            <div className="mt-1.5 md:hidden">
                              <StatusChip document={document} />
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className={classNames(cell, "hidden px-3 py-3 md:table-cell")}>
                        <span className="hidden xl:block">
                          <PipelineTrack document={document} labels />
                        </span>
                        <span className="xl:hidden">
                          <PipelineTrack document={document} />
                        </span>
                      </td>
                      <td className={classNames(cell, "hidden px-3 py-3 md:table-cell")}>
                        <StatusChip document={document} />
                      </td>
                      <td className={classNames(cell, "hidden px-3 py-3 text-right text-fg-muted tabular-nums xl:table-cell")}>{document.chunk_count || "–"}</td>
                      <td className={classNames(cell, "hidden px-3 py-3 whitespace-nowrap text-fg-muted xl:table-cell")}>
                        {document.indexed_at ? formatRelative(document.indexed_at) : "–"}
                      </td>
                      <td className={classNames(cell, "py-2 pr-3 pl-2", last && "rounded-br-xl")}>
                        {/* On a phone the three actions fold into one menu, which leaves the title room to breathe. */}
                        <div className="flex justify-end sm:hidden">
                          <Menu
                            label={`Actions for ${document.title}`}
                            trigger={(props) => (
                              <IconButton label={`Actions for ${document.title}`} {...props}>
                                <Ellipsis className="size-4" aria-hidden />
                              </IconButton>
                            )}
                          >
                            <MenuItem icon={<Layers className="size-3.5" aria-hidden />} onSelect={() => navigate(`/knowledge/documents/${document.id}`)}>
                              Inspect chunks
                            </MenuItem>
                            <MenuItem
                              icon={<RefreshCw className="size-3.5" aria-hidden />}
                              disabled={isProcessing(document) || working}
                              onSelect={() => void run(() => api.reindexDocument(document.id), "The document could not be re-indexed.", "Re-indexing started")}
                            >
                              Re-index
                            </MenuItem>
                            <MenuItem icon={<Trash2 className="size-3.5" aria-hidden />} danger onSelect={() => setDialog({ kind: "delete-document", document })}>
                              Delete
                            </MenuItem>
                          </Menu>
                        </div>
                        <div className="hidden justify-end gap-0.5 sm:flex">
                          <Tooltip label="Inspect chunks">
                            <Link
                              to={`/knowledge/documents/${document.id}`}
                              aria-label={`Inspect the chunks of ${document.title}`}
                              className="inline-flex size-8 items-center justify-center rounded-md text-fg-subtle transition-colors duration-150 ease-standard hover:bg-wash-strong hover:text-accent-fg"
                            >
                              <Layers className="size-4" aria-hidden />
                            </Link>
                          </Tooltip>
                          <IconButton
                            label={`Re-index ${document.title}`}
                            className="hover:bg-wash-strong"
                            disabled={isProcessing(document) || working}
                            onClick={() => void run(() => api.reindexDocument(document.id), "The document could not be re-indexed.", "Re-indexing started")}
                          >
                            <RefreshCw className="size-4" aria-hidden />
                          </IconButton>
                          <IconButton label={`Delete ${document.title}`} className="hover:bg-danger-soft hover:text-danger-fg" onClick={() => setDialog({ kind: "delete-document", document })}>
                            <Trash2 className="size-4" aria-hidden />
                          </IconButton>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </Card>

      {dialog?.kind === "collection" && (
        <CollectionForm
          collection={dialog.collection}
          onClose={() => setDialog(null)}
          onSaved={() => {
            toast({ title: dialog.collection ? "Collection saved" : "Collection created" });
            setDialog(null);
            void refresh();
          }}
        />
      )}
      {dialog?.kind === "delete-document" && (
        <Modal
          title="Delete document?"
          description={`“${dialog.document.title}”, its ${dialog.document.chunk_count} chunks and its index entries will be removed. Past answers keep the passages they cited.`}
          onClose={() => setDialog(null)}
          footer={
            <>
              <Button onClick={() => setDialog(null)}>Cancel</Button>
              <Button variant="danger" loading={working} onClick={() => void run(() => api.deleteDocument(dialog.document.id), "The document could not be deleted.", "Document deleted")}>
                Delete document
              </Button>
            </>
          }
        />
      )}
      {dialog?.kind === "delete-collection" && (
        <Modal
          title="Delete collection?"
          description={`“${dialog.collection.name}” and its ${dialog.collection.document_count} documents will be removed from the knowledge base.`}
          onClose={() => setDialog(null)}
          footer={
            <>
              <Button onClick={() => setDialog(null)}>Cancel</Button>
              <Button
                variant="danger"
                loading={working}
                onClick={() =>
                  void run(
                    async () => {
                      await api.deleteCollection(dialog.collection.id);
                      setSelectedId(null);
                    },
                    "The collection could not be deleted.",
                    "Collection deleted",
                  )
                }
              >
                Delete collection
              </Button>
            </>
          }
        />
      )}
    </Page>
  );
}
