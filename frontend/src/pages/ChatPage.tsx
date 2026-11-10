import { ArrowUpRight } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { TopBar } from "../components/AppShell";
import { LogoMark } from "../components/brand";
import { Drawer } from "../components/overlays";
import { Button, ErrorNotice, Skeleton } from "../components/ui";
import { Composer } from "../features/chat/Composer";
import { AssistantMessage, PendingAnswer, UserMessage } from "../features/chat/MessageView";
import { SourcePanel } from "../features/chat/SourcePanel";
import { api, ApiError } from "../lib/api";
import { useConversations } from "../lib/conversations";
import { classNames } from "../lib/format";
import { useMediaQuery, usePersistentState } from "../lib/hooks";
import { useSession } from "../lib/session";
import type { Collection, EngineInfo, Message } from "../lib/types";

interface Pending {
  question: string;
  text: string;
  phase: "searching" | "writing";
  engine: EngineInfo | null;
}

interface Selection {
  messageId: number;
  number: number;
  /** Incremented on every choice, so that choosing the same citation again pulses the passage again. */
  pulse: number;
  /** Incremented when a citation is chosen in the conversation (not when a tab of the panel is). */
  opened: number;
  viaKeyboard: boolean;
}

const PANEL_MIN = 360;
const PANEL_MAX = 680;
const PANEL_DEFAULT = 464;
const CHAT_MIN = 420; // the conversation never gets narrower than this while the panel is resized

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function isPanelWidth(value: unknown): value is number {
  return typeof value === "number" && value >= PANEL_MIN && value <= PANEL_MAX;
}

/** The divider between the conversation and the docked source panel: drag it, or use the arrow keys. */
function ResizeHandle({ width, onResize }: { width: number; onResize: (width: number) => void }) {
  const [dragging, setDragging] = useState(false);
  const start = useRef({ x: 0, width: 0 });

  const limit = (next: number, element: HTMLElement) => {
    const available = (element.parentElement?.clientWidth ?? window.innerWidth) - CHAT_MIN;
    return Math.round(Math.min(Math.max(next, PANEL_MIN), Math.max(PANEL_MIN, Math.min(PANEL_MAX, available))));
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    start.current = { x: event.clientX, width };
    setDragging(true);
  };
  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    onResize(limit(start.current.width + (start.current.x - event.clientX), event.currentTarget));
  };
  const stop = () => setDragging(false);

  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 48 : 16;
    let next: number | null = null;
    if (event.key === "ArrowLeft") next = width + step;
    else if (event.key === "ArrowRight") next = width - step;
    else if (event.key === "Home") next = PANEL_MAX;
    else if (event.key === "End") next = PANEL_MIN;
    else if (event.key === "Enter") next = PANEL_DEFAULT;
    if (next == null) return;
    event.preventDefault();
    onResize(limit(next, event.currentTarget));
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize the source panel"
      aria-valuemin={PANEL_MIN}
      aria-valuemax={PANEL_MAX}
      aria-valuenow={width}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={stop}
      onPointerCancel={stop}
      onDoubleClick={(event) => onResize(limit(PANEL_DEFAULT, event.currentTarget))}
      onKeyDown={onKeyDown}
      className="group/handle relative z-10 -mx-1 w-2 shrink-0 cursor-col-resize touch-none select-none focus-visible:outline-none"
    >
      <span
        aria-hidden
        className={classNames(
          "absolute inset-y-0 left-1/2 -translate-x-1/2 transition-[width,background-color] duration-150 ease-standard",
          dragging ? "w-0.5 bg-accent" : "w-px bg-line group-hover/handle:w-0.5 group-hover/handle:bg-accent group-focus-visible/handle:w-0.5 group-focus-visible/handle:bg-focus",
        )}
      />
    </div>
  );
}

function ConversationSkeleton() {
  return (
    <div role="status" aria-label="Loading conversation" className="mx-auto max-w-[46rem] space-y-8 px-4 py-8 sm:px-6">
      {[0, 1].map((row) => (
        <div key={row} className="space-y-6">
          <div className="flex justify-end">
            <Skeleton className="h-10 w-64 rounded-2xl" />
          </div>
          <div className="flex gap-3.5">
            <Skeleton className="hidden size-7 rounded-lg sm:block" />
            <div className="flex-1 space-y-2.5 pt-1">
              <Skeleton className="h-3.5 w-full" />
              <Skeleton className="h-3.5 w-11/12" />
              <Skeleton className="h-3.5 w-4/6" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export function ChatPage() {
  const params = useParams();
  const activeId = params.conversationId ? Number(params.conversationId) : null;
  const navigate = useNavigate();
  const { user, meta } = useSession();
  const { conversations, add, retitle, refresh } = useConversations();
  const isAdmin = user?.role === "admin";

  const [collections, setCollections] = useState<Collection[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [scope, setScope] = useState<number | null>(null);

  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [askError, setAskError] = useState<{ question: string; message: string } | null>(null);
  const [selected, setSelected] = useState<Selection | null>(null);
  /** The answer that has just finished streaming; it replaces the pending one without animating in again. */
  const [settledId, setSettledId] = useState<number | null>(null);
  const [announcement, setAnnouncement] = useState("");

  const docked = useMediaQuery("(min-width: 1280px)");
  const tablet = useMediaQuery("(min-width: 768px)");
  const [panelWidth, setPanelWidth] = usePersistentState("sourcewise-source-width", PANEL_DEFAULT, isPanelWidth);

  /** The conversation whose messages are currently in state (so a conversation we just created is not re-fetched). */
  const loadedId = useRef<number | null>(null);
  const stream = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  /** The control that opened the source panel; focus returns to it when the panel closes. */
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    api.collections().then(setCollections).catch(() => undefined);
    api.suggestions().then(setSuggestions).catch(() => undefined);
    return () => stream.current?.abort();
  }, []);

  // Load the conversation named in the URL.
  useEffect(() => {
    if (activeId === loadedId.current) return;
    stream.current?.abort();
    setPending(null);
    setAskError(null);
    setSelected(null);
    setLoadError(null);
    setSettledId(null);
    loadedId.current = activeId;
    if (activeId == null) {
      setMessages([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api
      .conversation(activeId)
      .then((detail) => {
        if (!cancelled) setMessages(detail.messages);
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoadError(errorMessage(error, "Could not load this conversation."));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeId]);

  // Keep the newest content in view.
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages.length, pending?.text, pending?.question, askError]);

  // Opening the source panel narrows the chat column and re-wraps it; keep the cited answer in view.
  const selectedMessageId = selected?.messageId ?? null;
  useEffect(() => {
    if (selectedMessageId == null) return;
    const frame = window.requestAnimationFrame(() =>
      document.getElementById(`message-${selectedMessageId}`)?.scrollIntoView({ block: "nearest" }),
    );
    return () => window.cancelAnimationFrame(frame);
  }, [selectedMessageId]);

  const send = async (question: string) => {
    if (pending) return;
    setAskError(null);

    let conversationId = activeId;
    if (conversationId == null) {
      try {
        const created = await api.createConversation();
        conversationId = created.id;
        loadedId.current = created.id;
        setMessages([]);
        add(created);
        navigate(`/chat/${created.id}`);
      } catch (error) {
        setAskError({ question, message: errorMessage(error, "Could not start a conversation.") });
        return;
      }
    }

    const controller = new AbortController();
    stream.current = controller;
    let asked: Message | null = null;
    setPending({ question, text: "", phase: "searching", engine: meta?.engine ?? null });
    setAnnouncement("Searching the knowledge base.");

    await api.askStream(
      conversationId,
      { content: question, collection_ids: scope == null ? null : [scope] },
      {
        onStart: (data) => {
          asked = data.user_message;
          setPending((current) => current && { ...current, engine: data.engine });
          retitle(data.conversation.id, data.conversation.title);
        },
        onDelta: (text) => {
          setPending((current) => current && { ...current, phase: "writing", text: current.text + text });
          setAnnouncement("Writing the answer.");
        },
        onReset: (engine) => setPending((current) => current && { ...current, phase: "searching", text: "", engine }),
        onDone: (answer) => {
          setSettledId(answer.id);
          setMessages((current) => [...current, ...(asked ? [asked] : []), answer]);
          setPending(null);
          setAnnouncement(
            answer.abstained
              ? "The assistant replied that the knowledge base does not cover this question."
              : `The answer is ready, with ${answer.citations.length} ${answer.citations.length === 1 ? "source" : "sources"}.`,
          );
          refresh();
        },
        onError: (message) => {
          setMessages((current) => (asked ? [...current, asked] : current));
          setPending(null);
          setAskError({ question, message });
          setAnnouncement("The question could not be answered.");
        },
      },
      controller.signal,
    );
  };

  const giveFeedback = async (message: Message, value: -1 | 0 | 1) => {
    const previous = message.feedback;
    const apply = (feedback: number | null) =>
      setMessages((current) => current.map((item) => (item.id === message.id ? { ...item, feedback } : item)));
    apply(value === 0 ? null : value); // optimistic
    try {
      await api.feedback(message.id, value);
    } catch {
      apply(previous);
    }
  };

  const cite = useCallback((messageId: number, number: number, viaKeyboard: boolean) => {
    if (document.activeElement instanceof HTMLElement && !document.activeElement.closest("aside")) opener.current = document.activeElement;
    setSelected((current) => ({ messageId, number, viaKeyboard, pulse: (current?.pulse ?? 0) + 1, opened: (current?.opened ?? 0) + 1 }));
  }, []);

  const closeSource = useCallback(() => {
    setSelected(null);
    const target = opener.current;
    opener.current = null;
    if (target?.isConnected) target.focus({ preventScroll: true });
  }, []);

  const activeConversation = conversations?.find((item) => item.id === activeId) ?? null;
  const selectedMessage = selected ? messages.find((item) => item.id === selected.messageId) ?? null : null;
  const isEmpty = !loading && !loadError && messages.length === 0 && !pending && !askError;
  const firstName = user?.name.split(" ")[0];

  const panel =
    selected && selectedMessage ? (
      <SourcePanel
        citations={selectedMessage.citations}
        activeNumber={selected.number}
        pulse={selected.pulse}
        autoFocus={!docked || selected.viaKeyboard}
        openedAt={selected.opened}
        onSelect={(number) => setSelected((current) => current && { ...current, number, pulse: current.pulse + 1 })}
        onClose={closeSource}
        canInspect={isAdmin}
      />
    ) : null;

  // While the drawer slides out, it keeps showing the source it was closed on.
  const lastPanel = useRef(panel);
  if (panel) lastPanel.current = panel;

  return (
    <div className="flex h-full">
      <section className="flex min-w-0 flex-1 flex-col" aria-label="Chat">
        <div className="min-h-0 flex-1 scroll-pt-16 overflow-y-auto">
          <TopBar>
            <h1 className="truncate text-base font-semibold text-fg">{activeConversation?.title ?? "New conversation"}</h1>
          </TopBar>

          {loading && <ConversationSkeleton />}
          {loadError && (
            <div className="mx-auto max-w-[46rem] px-4 py-8 sm:px-6">
              <ErrorNotice message={loadError} />
              <Button className="mt-4" onClick={() => navigate("/chat")}>
                Start a new conversation
              </Button>
            </div>
          )}

          {isEmpty && (
            // Anchored from the top rather than centred: the starter questions arrive after the greeting and must not move it.
            <div className="mx-auto max-w-[46rem] px-4 pt-[clamp(2.5rem,13vh,8rem)] pb-10 sm:px-6">
              <LogoMark className="size-10" />
              <h2 className="mt-6 text-3xl font-semibold tracking-tighter text-fg">
                {firstName ? `Hello ${firstName}, what would you like to know?` : "What would you like to know?"}
              </h2>
              <p className="mt-3 max-w-xl text-md text-fg-muted">
                Ask about a policy, a procedure or a product detail. Every answer cites the passage it came from, and if the
                documents do not cover your question you will be told so.
              </p>
              {suggestions.length > 0 && (
                <>
                  <h3 className="mt-10 text-2xs font-medium tracking-caps text-fg-subtle uppercase">Try asking</h3>
                  <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                    {suggestions.map((suggestion) => (
                      <li key={suggestion}>
                        <button
                          type="button"
                          onClick={() => void send(suggestion)}
                          className="group/ask flex h-full w-full items-start gap-3 rounded-xl border border-line bg-card px-3.5 py-3 text-left text-base text-fg shadow-xs transition-[border-color,background-color,box-shadow] duration-150 ease-standard hover:border-accent-line hover:bg-accent-soft hover:shadow-sm"
                        >
                          <span className="min-w-0 flex-1">{suggestion}</span>
                          <ArrowUpRight
                            className="mt-0.5 size-4 shrink-0 text-fg-faint transition-[color,transform] duration-150 ease-standard group-hover/ask:translate-x-0.5 group-hover/ask:-translate-y-0.5 group-hover/ask:text-accent-fg"
                            aria-hidden
                          />
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}

          {!loading && !loadError && !isEmpty && (
            <div className="mx-auto max-w-[46rem] space-y-7 px-4 pt-7 pb-10 sm:px-6">
              {messages.map((message) =>
                message.role === "user" ? (
                  <UserMessage key={message.id} content={message.content} />
                ) : (
                  <AssistantMessage
                    key={message.id}
                    id={`message-${message.id}`}
                    message={message}
                    activeCitation={selected?.messageId === message.id ? selected.number : null}
                    isAdmin={isAdmin}
                    animate={message.id !== settledId}
                    onCite={(number, viaKeyboard) => cite(message.id, number, viaKeyboard)}
                    onFeedback={(value) => void giveFeedback(message, value)}
                  />
                ),
              )}
              {pending && (
                <>
                  <UserMessage content={pending.question} />
                  <PendingAnswer text={pending.text} phase={pending.phase} engine={pending.engine} />
                </>
              )}
              {askError && (
                <ErrorNotice
                  message={`${askError.message} Your question was not answered.`}
                  onRetry={() => void send(askError.question)}
                />
              )}
              <div ref={bottom} />
            </div>
          )}
        </div>

        <p role="status" aria-live="polite" className="sr-only">
          {announcement}
        </p>
        <Composer disabled={pending !== null || loading} collections={collections} scope={scope} onScopeChange={setScope} onSend={(question) => void send(question)} />
      </section>

      {/* Wide screens dock the source beside the conversation; narrower ones slide it over (from the right, or as a bottom sheet on phones). */}
      {docked ? (
        panel && (
          <>
            <ResizeHandle width={panelWidth} onResize={setPanelWidth} />
            <div className="shrink-0 animate-slide-right" style={{ width: panelWidth }}>
              {panel}
            </div>
          </>
        )
      ) : (
        <Drawer open={panel != null} side={tablet ? "right" : "bottom"} label="Source" onClose={closeSource}>
          {panel ?? lastPanel.current}
        </Drawer>
      )}
    </div>
  );
}
