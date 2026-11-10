import { Check, Ellipsis, Pencil, Trash2, X } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { Link, useMatch, useNavigate } from "react-router-dom";

import { ConversationArt } from "../../components/illustrations";
import { Menu, MenuItem, Modal } from "../../components/overlays";
import { useToast } from "../../components/toast";
import { Button, ErrorNotice, IconButton, Skeleton } from "../../components/ui";
import { useConversations } from "../../lib/conversations";
import { classNames } from "../../lib/format";
import type { Conversation } from "../../lib/types";

const DAY = 24 * 60 * 60 * 1000;

/** "Today", "Yesterday", "Previous 7 days" or "Older", by the day a conversation was last active. */
function groupOf(conversation: Conversation, startOfToday: number): string {
  const updated = new Date(conversation.updated_at).getTime();
  if (updated >= startOfToday) return "Today";
  if (updated >= startOfToday - DAY) return "Yesterday";
  if (updated >= startOfToday - 7 * DAY) return "Previous 7 days";
  return "Older";
}

/** The signed-in user's conversations, grouped by day, with rename and delete on each row. */
export function ConversationList({ onNavigate }: { onNavigate?: () => void }) {
  const { conversations, error, refresh, rename, remove } = useConversations();
  const match = useMatch("/chat/:conversationId");
  const activeId = match?.params.conversationId ? Number(match.params.conversationId) : null;
  const navigate = useNavigate();
  const toast = useToast();

  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [deleting, setDeleting] = useState<Conversation | null>(null);

  const groups = useMemo(() => {
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const result: { name: string; items: Conversation[] }[] = [];
    for (const conversation of conversations ?? []) {
      const name = groupOf(conversation, startOfToday);
      const last = result[result.length - 1];
      if (last?.name === name) last.items.push(conversation);
      else result.push({ name, items: [conversation] });
    }
    return result;
  }, [conversations]);

  const submitRename = async (event: FormEvent) => {
    event.preventDefault();
    const title = draft.trim();
    const id = editingId;
    setEditingId(null);
    if (id != null && title) await rename(id, title);
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    const target = deleting;
    setDeleting(null);
    if (await remove(target.id)) {
      toast({ title: "Conversation deleted" });
      if (target.id === activeId) navigate("/chat");
    }
  };

  return (
    <div className="fade-mask-y min-h-0 flex-1 overflow-y-auto px-3 pt-2 pb-3">
      {error && <ErrorNotice message={error} onRetry={refresh} className="mb-2" />}

      {!error && conversations === null && (
        <div role="status" aria-label="Loading conversations" className="space-y-2.5 px-2.5 pt-2">
          {[78, 92, 64, 85, 70].map((width) => (
            <Skeleton key={width} className="h-3.5" style={{ width: `${width}%` }} />
          ))}
        </div>
      )}

      {conversations?.length === 0 && (
        <div className="flex flex-col items-center px-3 pt-6 text-center">
          <ConversationArt className="h-16 w-[5.5rem]" />
          <p className="mt-3 text-sm font-medium text-fg">No conversations yet</p>
          <p className="mt-0.5 text-xs text-fg-subtle">Ask a question to start one.</p>
        </div>
      )}

      {groups.map((group) => (
        <section key={group.name} aria-label={group.name} className="mb-3 last:mb-0">
          <h3 className="px-2.5 pt-1 pb-1 text-2xs font-medium tracking-caps text-fg-subtle uppercase">{group.name}</h3>
          <ul className="space-y-px">
            {group.items.map((conversation) => {
              const active = conversation.id === activeId;
              if (editingId === conversation.id) {
                return (
                  <li key={conversation.id}>
                    <form onSubmit={submitRename} className="flex items-center gap-0.5 rounded-md bg-thumb py-0.5 pr-0.5 pl-1 shadow-focus">
                      <input
                        autoFocus
                        aria-label="Conversation title"
                        value={draft}
                        maxLength={200}
                        onChange={(event) => setDraft(event.target.value)}
                        onKeyDown={(event) => event.key === "Escape" && setEditingId(null)}
                        className="h-7 min-w-0 flex-1 bg-transparent px-1.5 text-sm text-fg focus:outline-none"
                      />
                      <IconButton size="sm" label="Save title" type="submit">
                        <Check className="size-3.5" aria-hidden />
                      </IconButton>
                      <IconButton size="sm" label="Cancel" onClick={() => setEditingId(null)}>
                        <X className="size-3.5" aria-hidden />
                      </IconButton>
                    </form>
                  </li>
                );
              }
              return (
                <li key={conversation.id} className="group/row relative">
                  <Link
                    to={`/chat/${conversation.id}`}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={classNames(
                      "flex h-8 items-center rounded-md pr-9 pl-2.5 text-sm transition-colors duration-150 ease-standard",
                      active
                        ? "bg-thumb font-medium text-fg shadow-xs ring-1 ring-line"
                        : "text-fg-muted group-focus-within/row:bg-wash group-focus-within/row:text-fg group-hover/row:bg-wash group-hover/row:text-fg",
                    )}
                  >
                    <span className="truncate">{conversation.title}</span>
                  </Link>
                  {/* Shown on hover, on keyboard focus, and while its menu is open. */}
                  <div className="absolute inset-y-0 right-0.5 flex items-center opacity-0 transition-opacity duration-150 group-focus-within/row:opacity-100 group-hover/row:opacity-100 has-[[data-open=true]]:opacity-100">
                    <Menu
                      label={`Actions for “${conversation.title}”`}
                      trigger={(props) => (
                        <IconButton size="sm" label={`Actions for “${conversation.title}”`} tooltipSide="right" {...props}>
                          <Ellipsis className="size-4" aria-hidden />
                        </IconButton>
                      )}
                    >
                      <MenuItem
                        icon={<Pencil className="size-3.5" aria-hidden />}
                        onSelect={() => {
                          setEditingId(conversation.id);
                          setDraft(conversation.title);
                        }}
                      >
                        Rename
                      </MenuItem>
                      <MenuItem icon={<Trash2 className="size-3.5" aria-hidden />} danger onSelect={() => setDeleting(conversation)}>
                        Delete
                      </MenuItem>
                    </Menu>
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      ))}

      {deleting && (
        <Modal
          title="Delete conversation?"
          description={`“${deleting.title}” and its answers will be removed permanently.`}
          onClose={() => setDeleting(null)}
          footer={
            <>
              <Button onClick={() => setDeleting(null)}>Cancel</Button>
              <Button variant="danger" onClick={() => void confirmDelete()}>
                Delete conversation
              </Button>
            </>
          }
        />
      )}
    </div>
  );
}
