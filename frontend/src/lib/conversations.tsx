import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, ApiError } from "./api";
import type { Conversation } from "./types";

interface ConversationsState {
  /** The signed-in user's conversations, newest first; null while the first request is running. */
  conversations: Conversation[] | null;
  error: string | null;
  refresh: () => void;
  /** Put a conversation that was just created at the top of the list. */
  add: (conversation: Conversation) => void;
  /** Update a title locally (the server already knows it). */
  retitle: (id: number, title: string) => void;
  /** Rename on the server; resolves to false (and sets `error`) when that fails. */
  rename: (id: number, title: string) => Promise<boolean>;
  /** Delete on the server; resolves to false (and sets `error`) when that fails. */
  remove: (id: number) => Promise<boolean>;
}

const ConversationsContext = createContext<ConversationsState | null>(null);

function message(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

/**
 * The conversation list, shared by the sidebar, the chat page and the command palette.
 * Conversations are private to their owner; the server only ever returns the caller's own.
 */
export function ConversationsProvider({ children }: { children: ReactNode }) {
  const [conversations, setConversations] = useState<Conversation[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setError(null);
    api
      .conversations()
      .then(setConversations)
      .catch((caught: unknown) => setError(message(caught, "Could not load your conversations.")));
  }, []);

  useEffect(() => refresh(), [refresh]);

  const add = useCallback((conversation: Conversation) => {
    setConversations((current) => [conversation, ...(current ?? []).filter((item) => item.id !== conversation.id)]);
  }, []);

  const retitle = useCallback((id: number, title: string) => {
    setConversations((current) => current?.map((item) => (item.id === id ? { ...item, title } : item)) ?? current);
  }, []);

  const rename = useCallback(
    async (id: number, title: string) => {
      try {
        const updated = await api.renameConversation(id, title);
        retitle(id, updated.title);
        return true;
      } catch (caught) {
        setError(message(caught, "Could not rename the conversation."));
        return false;
      }
    },
    [retitle],
  );

  const remove = useCallback(async (id: number) => {
    try {
      await api.deleteConversation(id);
      setConversations((current) => current?.filter((item) => item.id !== id) ?? current);
      return true;
    } catch (caught) {
      setError(message(caught, "Could not delete the conversation."));
      return false;
    }
  }, []);

  const value = useMemo(
    () => ({ conversations, error, refresh, add, retitle, rename, remove }),
    [conversations, error, refresh, add, retitle, rename, remove],
  );
  return <ConversationsContext.Provider value={value}>{children}</ConversationsContext.Provider>;
}

export function useConversations(): ConversationsState {
  const value = useContext(ConversationsContext);
  if (!value) throw new Error("useConversations must be used inside <ConversationsProvider>");
  return value;
}
