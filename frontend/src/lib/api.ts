import type {
  Collection,
  Conversation,
  ConversationDetail,
  DocumentChunks,
  EngineInfo,
  Insights,
  KbDocument,
  Message,
  Meta,
  StreamCitation,
  StreamRetrieval,
  StreamStart,
  User,
} from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

let unauthorizedHandler: (() => void) | null = null;

/** Called by the auth provider so that an expired session anywhere returns the user to sign-in. */
export function onUnauthorized(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

function describeError(payload: unknown, status: number): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      // FastAPI validation errors: [{loc: [...], msg: "..."}]
      const messages = detail
        .map((item) => (item && typeof item === "object" && "msg" in item ? String((item as { msg: unknown }).msg) : ""))
        .filter(Boolean);
      if (messages.length) return messages.join("; ");
    }
  }
  if (status === 413) return "The file is too large to upload.";
  return `The request failed (HTTP ${status}).`;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin" };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check that it is running and try again.");
  }
  if (response.status === 204) return undefined as T;

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && path !== "/auth/login") unauthorizedHandler?.();
    throw new ApiError(response.status, describeError(payload, response.status));
  }
  return payload as T;
}

export interface AnswerStreamHandlers {
  onStart?: (data: StreamStart) => void;
  onRetrieval?: (data: StreamRetrieval) => void;
  onDelta: (text: string) => void;
  onCitation?: (data: StreamCitation) => void;
  /** The engine was switched after a failure: discard the text streamed so far. */
  onReset?: (engine: EngineInfo) => void;
  onDone: (message: Message) => void;
  onError: (message: string) => void;
}

/**
 * Ask a question and consume the answer as a server-sent event stream.
 * EventSource cannot POST, so the stream is read from a fetch response body.
 */
async function askStream(
  conversationId: number,
  body: { content: string; collection_ids: number[] | null },
  handlers: AnswerStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`/api/conversations/${conversationId}/messages`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ ...body, stream: true }),
      signal,
    });
  } catch (error) {
    if (signal?.aborted) return;
    handlers.onError(error instanceof Error && error.name !== "TypeError" ? error.message : "Cannot reach the server.");
    return;
  }
  if (!response.ok || !response.body) {
    const payload: unknown = await response.json().catch(() => null);
    if (response.status === 401) unauthorizedHandler?.();
    handlers.onError(describeError(payload, response.status));
    return;
  }

  let finished = false;
  const dispatch = (block: string) => {
    let event = "message";
    let data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) event = line.slice(7).trim();
      else if (line.startsWith("data: ")) data += line.slice(6);
    }
    if (!data) return;
    const payload = JSON.parse(data) as Record<string, unknown>;
    switch (event) {
      case "start":
        handlers.onStart?.(payload as unknown as StreamStart);
        break;
      case "retrieval":
        handlers.onRetrieval?.(payload as unknown as StreamRetrieval);
        break;
      case "delta":
        handlers.onDelta(String(payload.text ?? ""));
        break;
      case "citation":
        handlers.onCitation?.(payload as unknown as StreamCitation);
        break;
      case "reset":
        handlers.onReset?.(payload.engine as EngineInfo);
        break;
      case "done":
        finished = true;
        handlers.onDone(payload.message as Message);
        break;
      case "error":
        finished = true;
        handlers.onError(String(payload.message ?? "The answer could not be generated."));
        break;
    }
  };

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        dispatch(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf("\n\n");
      }
    }
  } catch {
    if (signal?.aborted) return;
  }
  if (!finished && !signal?.aborted) {
    handlers.onError("The connection was interrupted before the answer finished.");
  }
}

/**
 * Upload one document. XMLHttpRequest is used instead of fetch because it reports how much of
 * the file has been sent, which the upload list shows as a progress bar.
 */
function uploadDocument(collectionId: number, file: File, onProgress?: (fraction: number) => void): Promise<KbDocument> {
  return new Promise<KbDocument>((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    form.append("collection_id", String(collectionId));

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/documents");
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) onProgress?.(event.loaded / event.total);
    };
    xhr.onload = () => {
      let payload: unknown = null;
      try {
        payload = JSON.parse(xhr.responseText);
      } catch {
        payload = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(1);
        resolve(payload as KbDocument);
        return;
      }
      if (xhr.status === 401) unauthorizedHandler?.();
      reject(new ApiError(xhr.status, describeError(payload, xhr.status)));
    };
    xhr.onerror = () => reject(new ApiError(0, "Cannot reach the server. Check that it is running and try again."));
    xhr.send(form);
  });
}

export const api = {
  meta: () => request<Meta>("GET", "/meta"),

  /** The signed-in user, or null. (Unlike /auth/me this is not an error when signed out.) */
  session: () => request<{ user: User | null }>("GET", "/auth/session").then((body) => body.user),
  login: (email: string, password: string) => request<User>("POST", "/auth/login", { email, password }),
  logout: () => request<void>("POST", "/auth/logout"),

  collections: () => request<Collection[]>("GET", "/collections"),
  createCollection: (name: string, description: string) =>
    request<Collection>("POST", "/collections", { name, description }),
  updateCollection: (id: number, name: string, description: string) =>
    request<Collection>("PATCH", `/collections/${id}`, { name, description }),
  deleteCollection: (id: number) => request<void>("DELETE", `/collections/${id}`),

  documents: () => request<KbDocument[]>("GET", "/documents"),
  document: (id: number) => request<KbDocument>("GET", `/documents/${id}`),
  documentChunks: (id: number) => request<DocumentChunks>("GET", `/documents/${id}/chunks`),
  uploadDocument,
  reindexDocument: (id: number) => request<KbDocument>("POST", `/documents/${id}/reindex`),
  deleteDocument: (id: number) => request<void>("DELETE", `/documents/${id}`),

  conversations: () => request<Conversation[]>("GET", "/conversations"),
  conversation: (id: number) => request<ConversationDetail>("GET", `/conversations/${id}`),
  createConversation: () => request<Conversation>("POST", "/conversations", {}),
  renameConversation: (id: number, title: string) => request<Conversation>("PATCH", `/conversations/${id}`, { title }),
  deleteConversation: (id: number) => request<void>("DELETE", `/conversations/${id}`),
  askStream,
  feedback: (messageId: number, value: -1 | 0 | 1) =>
    request<Message>("POST", `/messages/${messageId}/feedback`, { value }),
  suggestions: () => request<string[]>("GET", "/suggestions"),

  insights: (days: number) => request<Insights>("GET", `/insights?days=${days}`),
};
