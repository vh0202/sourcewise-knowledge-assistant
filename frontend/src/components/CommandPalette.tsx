import { ChartColumn, CornerDownLeft, Library, LogOut, MessageSquare, Monitor, Moon, Search, SquarePen, Sun } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../lib/api";
import { useConversations } from "../lib/conversations";
import { classNames, formatRelative } from "../lib/format";
import { useSession } from "../lib/session";
import { useTheme } from "../lib/theme";
import type { KbDocument } from "../lib/types";
import { FileTypeIcon, fileKindName, Kbd } from "./ui";

interface PaletteItem {
  id: string;
  group: "Go to" | "Conversations" | "Documents" | "Actions";
  label: string;
  hint?: string;
  icon: ReactNode;
  run: () => void;
}

const GROUP_ORDER: PaletteItem["group"][] = ["Go to", "Conversations", "Documents", "Actions"];
const IDLE_LIMIT = 4; // rows per list while nothing has been typed
const SEARCH_LIMIT = 8;

/** Every word of the query must occur in the label; earlier matches rank higher. */
function score(label: string, words: string[]): number | null {
  const haystack = label.toLowerCase();
  let total = 0;
  for (const word of words) {
    const index = haystack.indexOf(word);
    if (index < 0) return null;
    total += index;
  }
  return total;
}

/** The label with the first occurrence of each query word emphasised. */
function Highlighted({ label, words }: { label: string; words: string[] }) {
  if (words.length === 0) return <>{label}</>;
  const lower = label.toLowerCase();
  const ranges = words
    .map((word) => ({ start: lower.indexOf(word), end: lower.indexOf(word) + word.length }))
    .filter((range) => range.start >= 0)
    .sort((a, b) => a.start - b.start);
  const pieces: ReactNode[] = [];
  let cursor = 0;
  for (const range of ranges) {
    if (range.start < cursor) continue; // overlapping matches: keep the first
    if (range.start > cursor) pieces.push(label.slice(cursor, range.start));
    pieces.push(
      <span key={range.start} className="font-semibold text-accent-fg">
        {label.slice(range.start, range.end)}
      </span>,
    );
    cursor = range.end;
  }
  pieces.push(label.slice(cursor));
  return <>{pieces}</>;
}

/** Ctrl/Cmd+K: jump to a conversation, a document or a page, or run a common action. */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;
  return <PaletteDialog onClose={onClose} />;
}

function PaletteDialog({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const listId = useId();
  const navigate = useNavigate();
  const { user, logout } = useSession();
  const { conversations } = useConversations();
  const { theme, preference, setPreference } = useTheme();
  const isAdmin = user?.role === "admin";

  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [documents, setDocuments] = useState<KbDocument[]>([]);

  useEffect(() => {
    const element = dialog.current;
    if (element && !element.open) element.showModal();
    return () => element?.close();
  }, []);

  // Only administrators may list documents; the server refuses everyone else.
  useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    api
      .documents()
      .then((result) => !cancelled && setDocuments(result))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [isAdmin]);

  const items = useMemo<PaletteItem[]>(() => {
    const icon = "size-4 text-fg-subtle";
    const all: PaletteItem[] = [
      { id: "new-chat", group: "Go to", label: "New chat", hint: "Start a new conversation", icon: <SquarePen className={icon} aria-hidden />, run: () => navigate("/chat") },
    ];
    if (isAdmin) {
      all.push(
        { id: "knowledge", group: "Go to", label: "Knowledge base", hint: "Documents and uploads", icon: <Library className={icon} aria-hidden />, run: () => navigate("/knowledge") },
        { id: "insights", group: "Go to", label: "Insights", hint: "Usage and knowledge gaps", icon: <ChartColumn className={icon} aria-hidden />, run: () => navigate("/insights") },
      );
    }
    for (const conversation of conversations ?? []) {
      all.push({
        id: `conversation-${conversation.id}`,
        group: "Conversations",
        label: conversation.title,
        hint: formatRelative(conversation.updated_at),
        icon: <MessageSquare className={icon} aria-hidden />,
        run: () => navigate(`/chat/${conversation.id}`),
      });
    }
    for (const document of documents) {
      all.push({
        id: `document-${document.id}`,
        group: "Documents",
        label: document.title,
        hint: `${document.collection_name} · ${fileKindName(document.kind)}`,
        icon: <FileTypeIcon kind={document.kind} size="sm" />,
        run: () => navigate(`/knowledge/documents/${document.id}`),
      });
    }
    all.push(
      theme === "dark"
        ? { id: "theme-light", group: "Actions", label: "Switch to light theme", icon: <Sun className={icon} aria-hidden />, run: () => setPreference("light") }
        : { id: "theme-dark", group: "Actions", label: "Switch to dark theme", icon: <Moon className={icon} aria-hidden />, run: () => setPreference("dark") },
    );
    if (preference !== "system") {
      all.push({ id: "theme-system", group: "Actions", label: "Use the system theme", icon: <Monitor className={icon} aria-hidden />, run: () => setPreference("system") });
    }
    all.push({ id: "sign-out", group: "Actions", label: "Sign out", hint: user?.email, icon: <LogOut className={icon} aria-hidden />, run: () => void logout() });
    return all;
  }, [conversations, documents, isAdmin, logout, navigate, preference, setPreference, theme, user?.email]);

  const words = useMemo(() => query.toLowerCase().split(/\s+/).filter(Boolean), [query]);

  const groups = useMemo(() => {
    return GROUP_ORDER.map((name) => {
      const inGroup = items.filter((item) => item.group === name);
      if (words.length === 0) {
        const limited = name === "Conversations" || name === "Documents" ? inGroup.slice(0, IDLE_LIMIT) : inGroup;
        return { name, items: limited };
      }
      const ranked = inGroup
        .map((item) => ({ item, rank: score(item.label, words) }))
        .filter((entry): entry is { item: PaletteItem; rank: number } => entry.rank != null)
        .sort((a, b) => a.rank - b.rank)
        .slice(0, SEARCH_LIMIT)
        .map((entry) => entry.item);
      return { name, items: ranked };
    }).filter((group) => group.items.length > 0);
  }, [items, words]);

  const flat = useMemo(() => groups.flatMap((group) => group.items), [groups]);
  const active = flat[Math.min(activeIndex, flat.length - 1)] ?? null;

  useEffect(() => setActiveIndex(0), [query]);

  useEffect(() => {
    if (!active) return;
    list.current?.querySelector(`[data-item="${active.id}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const run = (item: PaletteItem) => {
    onClose();
    item.run();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((index) => (flat.length ? (Math.min(index, flat.length - 1) + 1) % flat.length : 0));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) => (flat.length ? (Math.min(index, flat.length - 1) - 1 + flat.length) % flat.length : 0));
    } else if (event.key === "Home") {
      event.preventDefault();
      setActiveIndex(0);
    } else if (event.key === "End") {
      event.preventDefault();
      setActiveIndex(Math.max(flat.length - 1, 0));
    } else if (event.key === "Enter" && active && !event.nativeEvent.isComposing) {
      event.preventDefault();
      run(active);
    }
  };

  return (
    <dialog
      ref={dialog}
      aria-label="Command palette"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === dialog.current) onClose();
      }}
      className="mx-auto mt-[12vh] mb-auto w-[min(92vw,38rem)] animate-pop overflow-hidden rounded-2xl border border-line bg-raised p-0 shadow-xl"
    >
      <div className="flex items-center gap-3 border-b border-line px-4">
        <Search className="size-4 shrink-0 text-fg-subtle" aria-hidden />
        <input
          autoFocus
          role="combobox"
          aria-label="Search conversations, documents and pages"
          aria-expanded="true"
          aria-controls={listId}
          aria-activedescendant={active ? `${listId}-${active.id}` : undefined}
          aria-autocomplete="list"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={isAdmin ? "Search conversations, documents and pages" : "Search conversations and pages"}
          className="h-12 min-w-0 flex-1 bg-transparent text-md text-fg placeholder:text-fg-subtle focus:outline-none"
        />
        <Kbd>Esc</Kbd>
      </div>

      <div ref={list} id={listId} role="listbox" aria-label="Results" className="max-h-[min(58vh,30rem)] overflow-y-auto p-2">
        {groups.length === 0 && (
          <p className="px-3 py-8 text-center text-sm text-fg-muted">
            Nothing matches <span className="font-medium text-fg">“{query}”</span>.
          </p>
        )}
        {groups.map((group) => (
          <div key={group.name} role="group" aria-label={group.name} className="mb-1.5 last:mb-0">
            <p aria-hidden className="px-2.5 pt-2 pb-1 text-2xs font-medium tracking-caps text-fg-subtle uppercase">
              {group.name}
            </p>
            {group.items.map((item) => {
              const selected = item.id === active?.id;
              return (
                <div
                  key={item.id}
                  id={`${listId}-${item.id}`}
                  role="option"
                  aria-selected={selected}
                  data-item={item.id}
                  onPointerMove={() => setActiveIndex(flat.indexOf(item))}
                  onClick={() => run(item)}
                  className={classNames(
                    "flex h-10 cursor-pointer items-center gap-3 rounded-lg px-2.5 text-sm transition-colors duration-100",
                    selected ? "bg-wash-strong text-fg" : "text-fg",
                  )}
                >
                  <span className="flex w-5 shrink-0 items-center justify-center">{item.icon}</span>
                  <span className="min-w-0 flex-1 truncate">
                    <Highlighted label={item.label} words={words} />
                  </span>
                  {item.hint && (
                    <span className={classNames("hidden max-w-[45%] shrink-0 truncate text-xs sm:block", selected ? "text-fg-muted" : "text-fg-subtle")}>
                      {item.hint}
                    </span>
                  )}
                  <CornerDownLeft className={classNames("size-3.5 shrink-0 text-fg-subtle", selected ? "opacity-100" : "opacity-0")} aria-hidden />
                </div>
              );
            })}
          </div>
        ))}
      </div>

      <div className="flex items-center gap-4 border-t border-line bg-wash px-4 py-2 text-xs text-fg-subtle">
        <span className="flex items-center gap-1.5">
          <Kbd>↑</Kbd>
          <Kbd>↓</Kbd>
          to move
        </span>
        <span className="flex items-center gap-1.5">
          <Kbd>↵</Kbd>
          to open
        </span>
        <span className="ml-auto tabular-nums">
          {flat.length} {flat.length === 1 ? "result" : "results"}
        </span>
      </div>
    </dialog>
  );
}
